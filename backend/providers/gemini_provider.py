"""Google Gemini provider — fully implemented but disabled by default.

Enable this provider once the OpenAI slot is verified in production:

  1. Paste `GEMINI_API_KEY=...` into /app/backend/.env
  2. Set `ENABLE_GEMINI=true` (also in .env) OR flip the flag in
     `providers/registry.py`.
  3. `sudo supervisorctl restart backend`.

Uses the official `google-generativeai` SDK.

Resilience: unlike OpenAI and Mistral, Gemini previously had no request-level
timeout and no retry — a single slow or transient failure meant an immediate
FAILED, bounded only by the *outer* `Provider.timed_generate` deadline
(`GEMINI_PROVIDER_TIMEOUT_SECONDS`, default 60s, unchanged — see
`providers/base.py`). This module now adds its own, shorter, configurable
per-request timeout plus a single bounded retry on transient errors only,
mirroring the pattern already used by `mistral_provider.py`.
"""
from __future__ import annotations

import asyncio
import os
import time
import logging

from .base import Provider, ProviderResult, ProviderTimeoutError

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash"

# Internal, per-request timeout — deliberately shorter than the outer
# `execution_timeout_seconds` enforced by Provider.timed_generate (default
# 60s), so that even with one retry the whole call comfortably fits inside
# the outer deadline: DEFAULT_REQUEST_TIMEOUT_SECONDS * (1 + DEFAULT_MAX_RETRIES)
# + a short backoff = 25 + 0.5 + 25 = 50.5s < 60s. The outer timeout remains
# the hard ceiling regardless of how these two are configured.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 25.0
DEFAULT_MAX_RETRIES = 1
_RETRY_BACKOFF_BASE_SECONDS = 0.5

SYSTEM_FALLBACK = (
    "You are one participant in a multi-model AI consensus panel called AI Referee. "
    "Answer the user's question directly, precisely, and with your best reasoning. "
    "Keep the answer self-contained — the panel synthesises multiple answers afterwards."
)


class GeminiProvider(Provider):
    id = "model-c"
    label = "Gemini"
    codename = DEFAULT_MODEL
    provider_name = "Google DeepMind"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        request_timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.codename = model
        # BYOK: prefer explicit override, otherwise the platform key.
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.available = bool(self.api_key)
        self.request_timeout_seconds = _positive_float(
            request_timeout_seconds,
            os.environ.get("GEMINI_REQUEST_TIMEOUT_SECONDS"),
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        self.max_retries = _non_negative_int(
            max_retries,
            os.environ.get("GEMINI_MAX_RETRIES"),
            DEFAULT_MAX_RETRIES,
        )

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        if not self.available:
            raise RuntimeError("GEMINI_API_KEY is missing — cannot call Gemini")

        # Lazy-import so the module doesn't crash the server when the SDK isn't installed.
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "google-generativeai SDK is not installed. Run: pip install google-generativeai"
            ) from e

        # Transient-error classification depends on the same optional SDK, so
        # it is resolved lazily too, alongside `genai` itself.
        transient_errors = _transient_google_api_errors()

        genai.configure(api_key=self.api_key)
        sys_msg = system or SYSTEM_FALLBACK
        gmodel = genai.GenerativeModel(self.model, system_instruction=sys_msg)

        attempts = self.max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            log.info(
                "gemini_attempt_started attempt=%d max_attempts=%d "
                "request_timeout_seconds=%g",
                attempt, attempts, self.request_timeout_seconds,
            )
            start = time.perf_counter()
            try:
                resp = await asyncio.wait_for(
                    _call_once(gmodel, prompt),
                    timeout=self.request_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                log.warning(
                    "gemini_attempt_internal_timeout attempt=%d max_attempts=%d "
                    "duration_ms=%d request_timeout_seconds=%g",
                    attempt, attempts, duration_ms, self.request_timeout_seconds,
                )
                last_exc = exc
            except transient_errors as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                log.warning(
                    "gemini_transient_error attempt=%d max_attempts=%d "
                    "duration_ms=%d error_type=%s",
                    attempt, attempts, duration_ms, type(exc).__name__,
                )
                last_exc = exc
            except Exception as exc:  # noqa: BLE001
                # Anything not explicitly classified as transient above (auth
                # failure, invalid model/argument, safety/policy block, ...)
                # is permanent: never retried, propagated immediately.
                log.warning(
                    "gemini_permanent_error attempt=%d error_type=%s",
                    attempt, type(exc).__name__,
                )
                raise
            else:
                latency_ms = int((time.perf_counter() - start) * 1000)
                log.info(
                    "gemini_attempt_succeeded attempt=%d duration_ms=%d",
                    attempt, latency_ms,
                )
                return _provider_result_from_response(resp, self.model, latency_ms)

            if attempt < attempts:
                backoff = _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                log.info(
                    "gemini_retry_scheduled next_attempt=%d max_attempts=%d "
                    "backoff_seconds=%g",
                    attempt + 1, attempts, backoff,
                )
                await asyncio.sleep(backoff)

        log.warning("gemini_retries_exhausted attempts=%d", attempts)
        if isinstance(last_exc, asyncio.TimeoutError):
            raise ProviderTimeoutError(
                f"Gemini exceeded its internal {self.request_timeout_seconds:g}s "
                f"request timeout after {attempts} attempt(s)."
            ) from last_exc
        raise RuntimeError(
            f"Gemini request failed after {attempts} attempt(s) "
            f"({type(last_exc).__name__ if last_exc else 'unknown error'})."
        ) from last_exc


async def _call_once(gmodel, prompt: str):
    """Issue exactly one Gemini request — no timeout, no retry (both handled
    by the caller). Isolated so it can be wrapped in `asyncio.wait_for`."""
    try:
        return await gmodel.generate_content_async(prompt)  # type: ignore[attr-defined]
    except AttributeError:
        # Keep the deprecated SDK's synchronous compatibility path off the
        # event loop so the surrounding asyncio.wait_for can still enforce
        # its independent deadline.
        return await asyncio.to_thread(gmodel.generate_content, prompt)


def _provider_result_from_response(resp, model: str, latency_ms: int) -> ProviderResult:
    text = (getattr(resp, "text", "") or "").strip()
    usage = getattr(resp, "usage_metadata", None)
    input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
    total_tokens = int(getattr(usage, "total_token_count", 0) or (input_tokens + output_tokens)) if usage else 0
    citation_metadata = _extract_grounding_metadata(resp)

    return ProviderResult(
        text=text,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        model_used=model,
        is_mock=False,
        citation_metadata=citation_metadata,
    )


def _extract_grounding_metadata(response) -> list[dict[str, str]]:
    """Extract only grounding sources explicitly returned by Gemini."""
    output: list[dict[str, str]] = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        grounding = getattr(candidate, "grounding_metadata", None)
        chunks = getattr(grounding, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            url = getattr(web, "uri", None)
            title = getattr(web, "title", None)
            if not isinstance(url, str) or not url.strip():
                continue
            item = {"url": url.strip()}
            if isinstance(title, str) and title.strip():
                item["title"] = title.strip()[:300]
            output.append(item)
    return output


def _transient_google_api_errors() -> tuple[type[Exception], ...]:
    """Lazily resolve the Google API error types worth a single retry.

    Imported lazily (like the SDK itself) so this module still loads when
    google-generativeai isn't installed. Anything NOT in this set — auth
    failures (Unauthenticated/PermissionDenied), invalid model/argument
    (InvalidArgument/NotFound), safety/policy blocks
    (BlockedPromptException/StopCandidateException) — is permanent and must
    never be retried.
    """
    try:
        from google.api_core.exceptions import (
            BadGateway,
            DeadlineExceeded,
            GatewayTimeout,
            InternalServerError,
            ResourceExhausted,
            ServiceUnavailable,
        )
    except ImportError:
        return ()
    return (
        ResourceExhausted,    # 429 — rate limit / quota exceeded
        ServiceUnavailable,   # 503
        InternalServerError,  # 500
        DeadlineExceeded,     # SDK/transport-level deadline, not our own
        GatewayTimeout,       # 504
        BadGateway,           # 502
    )


def _positive_float(explicit: float | None, configured: str | None, default: float) -> float:
    try:
        value = float(explicit if explicit is not None else configured or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _non_negative_int(explicit: int | None, configured: str | None, default: int) -> int:
    try:
        value = int(explicit if explicit is not None else configured or default)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default
