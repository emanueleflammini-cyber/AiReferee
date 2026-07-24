"""Shared provider types and execution safety for AI Referee.

Every provider implements ``generate``. ``timed_generate`` records latency and
returns one explicit state: LIVE, FAILED, or MOCK. A failed live provider never
receives replacement text from another provider or from a demo template.
"""
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


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


class Provider(ABC):
    """Base class for every LLM provider."""

    id: str = ""
    label: str = ""
    codename: str = ""
    provider_name: str = ""

    def __init__(self) -> None:
        self.available: bool = False

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str,
    ) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError

    async def timed_generate(self, prompt: str, system: str) -> ProviderResult:
        """Run the provider without ever substituting fallback content."""
        start = time.perf_counter()
        try:
            result = await self.generate(prompt, system)
            if result.latency_ms <= 0:
                result.latency_ms = int((time.perf_counter() - start) * 1000)
            if not (result.text or "").strip():
                raise RuntimeError("Provider returned an empty response")
            result.provider_status = "MOCK" if result.is_mock else "LIVE"
            return result.with_computed_cost()
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                text="",
                latency_ms=int((time.perf_counter() - start) * 1000),
                is_mock=False,
                provider_status="FAILED",
                error=_safe_error_message(exc),
            )


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
