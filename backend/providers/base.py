"""Shared provider types and execution safety for AI Referee.

Every provider implements ``generate``. ``timed_generate`` records latency and
returns LIVE, FAILED, or MOCK. Timeouts are explicit FAILED results with a
safe timeout reason. A failed live provider never receives replacement text
from another provider or from a demo template.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


log = logging.getLogger(__name__)

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 60.0
PROVIDER_TIMEOUT_ENV_BY_ID = {
    "model-a": "OPENAI_PROVIDER_TIMEOUT_SECONDS",
    "model-c": "GEMINI_PROVIDER_TIMEOUT_SECONDS",
    "model-e": "MISTRAL_PROVIDER_TIMEOUT_SECONDS",
    "model-b": "ANTHROPIC_PROVIDER_TIMEOUT_SECONDS",
}


# --------------------------------------------------------------------------
# Provider result status values — early-synthesis foundation.
# --------------------------------------------------------------------------
# LIVE / FAILED / MOCK remain the only statuses Provider.timed_generate can
# ever produce (see the module docstring above — unchanged by this patch).
# PENDING is reserved for the *future* early-synthesis orchestrator: it
# means "the real provider call is still in flight, neither succeeded nor
# failed yet". It is defined here, as named constants, purely so nothing
# has to spell "PENDING" as a bare string once that orchestrator exists —
# nothing in this codebase produces or consumes it today. The synchronous
# compare_query flow in server.py always resolves every provider to one of
# the other three statuses (via this exact function) before a ModelResponse
# is ever built, so PENDING cannot appear in a CompareResponse today.
PROVIDER_STATUS_LIVE = "LIVE"
PROVIDER_STATUS_FAILED = "FAILED"
PROVIDER_STATUS_MOCK = "MOCK"
PROVIDER_STATUS_PENDING = "PENDING"

# Every status a provider result may carry, PENDING included for forward
# compatibility even though nothing produces it yet (see above).
PROVIDER_STATUSES = frozenset({
    PROVIDER_STATUS_LIVE,
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_MOCK,
    PROVIDER_STATUS_PENDING,
})

# Statuses that represent a *finished* provider call — everything except
# PENDING. Code that must never treat "still running" as "resolved"
# (synthesis eligibility, claim-analysis validation, cost accounting, ...)
# should check membership here rather than hardcoding the other three.
FINALIZED_PROVIDER_STATUSES = frozenset({
    PROVIDER_STATUS_LIVE,
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_MOCK,
})


def is_pending_status(status: str) -> bool:
    """True iff `status` is exactly the PENDING marker."""
    return status == PROVIDER_STATUS_PENDING


PRICING: dict[str, dict[str, float]] = {
    "gpt-5.5-mini": {"input": 0.15, "output": 0.60},
    "gpt-5.5": {"input": 2.50, "output": 10.00},
    "gpt-5.4": {"input": 1.50, "output": 6.00},
    "gpt-5.4-mini": {"input": 0.15, "output": 0.60},
    "gemini-3.1-pro-preview": {"input": 1.25, "output": 5.00},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # Mistral Small standard API list price in USD per 1M tokens
    # (input/output, checked against Mistral's official pricing page).
    "mistral-small-latest": {"input": 0.15, "output": 0.60},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "grok-3": {"input": 2.00, "output": 10.00},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the advisory USD cost for a provider call."""
    if not model:
        return 0.0
    pricing = PRICING.get(model)
    if not pricing:
        candidate = ""
        for key in PRICING:
            if model.startswith(key) and len(key) > len(candidate):
                candidate = key
        if candidate:
            pricing = PRICING[candidate]
    if not pricing:
        return 0.0
    return round(
        (input_tokens / 1_000_000) * pricing["input"]
        + (output_tokens / 1_000_000) * pricing["output"],
        6,
    )


def billable_provider_cost(result: "ProviderResult", status: str) -> float:
    """Return a displayable cost only for a usable provider response.

    A failed, timed-out, disabled, or empty response must not contribute a
    fabricated amount to the comparison total. DEMO responses remain eligible
    for backwards compatibility, although the bundled mocks report zero cost.
    """
    normalized_status = str(status or "").upper()
    if normalized_status not in {"LIVE", "MOCK"}:
        return 0.0
    if not (result.text or "").strip():
        return 0.0
    return max(0.0, float(result.cost_usd or 0.0))


@dataclass
class ProviderResult:
    text: str
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    is_mock: bool = False
    provider_status: str = "LIVE"
    error: Optional[str] = None
    # Provider-declared citation metadata only. It is normalized and validated
    # later; raw SDK objects and secrets must never be stored here.
    citation_metadata: list[dict[str, Any]] = field(default_factory=list)

    def with_computed_cost(self) -> "ProviderResult":
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens
        if self.cost_usd == 0.0 and self.model_used:
            self.cost_usd = estimate_cost(
                self.model_used,
                self.input_tokens,
                self.output_tokens,
            )
        return self


def make_pending_result() -> ProviderResult:
    """Construct a well-formed PENDING ProviderResult.

    Not called anywhere yet — Provider.timed_generate never produces
    PENDING today (see the status constants above). Provided so a future
    early-synthesis orchestrator has exactly one correct, tested way to
    represent "still running": no text, no cost, not mock. Enforces the
    invariant that PENDING must never carry synthetic/mock content.
    """
    return ProviderResult(text="", provider_status=PROVIDER_STATUS_PENDING, is_mock=False)


class ProviderTimeoutError(TimeoutError):
    """A provider exhausted its own request timeout and retry budget."""


class Provider(ABC):
    """Base class for every LLM provider."""

    id: str = ""
    label: str = ""
    codename: str = ""
    provider_name: str = ""

    def __init__(
        self,
        execution_timeout_seconds: float | None = None,
    ) -> None:
        self.available: bool = False
        self.execution_timeout_seconds = _provider_timeout_seconds(
            self.id,
            execution_timeout_seconds,
        )

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str,
    ) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError

    async def timed_generate(self, prompt: str, system: str) -> ProviderResult:
        """Run one provider within its deadline, without fake fallback."""
        start = time.perf_counter()
        timeout_seconds = self.execution_timeout_seconds
        log.info(
            "provider_started provider_id=%s provider_name=%s "
            "timeout_seconds=%g",
            self.id or "unknown",
            self.provider_name or self.label or "unknown",
            timeout_seconds,
        )
        try:
            result = await asyncio.wait_for(
                self.generate(prompt, system),
                timeout=timeout_seconds,
            )
            if result.latency_ms <= 0:
                result.latency_ms = int((time.perf_counter() - start) * 1000)
            if not (result.text or "").strip():
                raise RuntimeError("Provider returned an empty response")
            result.provider_status = "MOCK" if result.is_mock else "LIVE"
            log.info(
                "provider_completed provider_id=%s provider_name=%s "
                "status=%s duration_ms=%d",
                self.id or "unknown",
                self.provider_name or self.label or "unknown",
                result.provider_status,
                result.latency_ms,
            )
            return result.with_computed_cost()
        except ProviderTimeoutError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            log.warning(
                "provider_timeout provider_id=%s provider_name=%s "
                "duration_ms=%d timeout_scope=provider",
                self.id or "unknown",
                self.provider_name or self.label or "unknown",
                duration_ms,
            )
            return ProviderResult(
                text="",
                latency_ms=duration_ms,
                is_mock=False,
                provider_status="FAILED",
                error=_safe_error_message(exc),
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            log.warning(
                "provider_timeout provider_id=%s provider_name=%s "
                "duration_ms=%d timeout_seconds=%g",
                self.id or "unknown",
                self.provider_name or self.label or "unknown",
                duration_ms,
                timeout_seconds,
            )
            return ProviderResult(
                text="",
                latency_ms=duration_ms,
                is_mock=False,
                provider_status="FAILED",
                error=(
                    "Provider request timed out after "
                    f"{timeout_seconds:g} seconds."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - start) * 1000)
            log.warning(
                "provider_failed provider_id=%s provider_name=%s "
                "duration_ms=%d error_type=%s",
                self.id or "unknown",
                self.provider_name or self.label or "unknown",
                duration_ms,
                type(exc).__name__,
            )
            return ProviderResult(
                text="",
                latency_ms=duration_ms,
                is_mock=False,
                provider_status="FAILED",
                error=_safe_error_message(exc),
            )


def _provider_timeout_seconds(
    provider_id: str,
    explicit: float | None,
) -> float:
    if explicit is not None:
        return _positive_timeout(explicit, DEFAULT_PROVIDER_TIMEOUT_SECONDS)
    provider_env = PROVIDER_TIMEOUT_ENV_BY_ID.get(provider_id)
    configured = (
        os.environ.get(provider_env, "").strip()
        if provider_env
        else ""
    )
    if not configured:
        configured = os.environ.get(
            "PROVIDER_TIMEOUT_SECONDS",
            str(DEFAULT_PROVIDER_TIMEOUT_SECONDS),
        ).strip()
    return _positive_timeout(configured, DEFAULT_PROVIDER_TIMEOUT_SECONDS)


def _positive_timeout(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_error_message(exc: Exception) -> str:
    """Return a useful reason without exposing configured API keys."""
    message = str(exc).strip() or "Provider unavailable"
    for env_name in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "MISTRAL_API_KEY",
    ):
        secret = os.environ.get(env_name, "").strip()
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return f"{type(exc).__name__}: {message}"[:500]
