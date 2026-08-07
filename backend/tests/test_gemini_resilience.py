"""Gemini resilience hotfix — offline tests, no real API calls.

Covers the internal per-request timeout + single bounded retry added to
GeminiProvider (providers/gemini_provider.py) after two consecutive
production smoke-test failures ("Tempo massimo del provider superato",
60000 ms exactly). Gemini previously had no request-level timeout and no
retry, unlike Mistral (own httpx timeout + 2 retries).

Every test here replaces `gemini_provider._call_once` — the one function
that would actually reach the network — with a stub, so no real
Gemini/OpenAI/Mistral API call ever happens. `google.generativeai.configure()`
/ `GenerativeModel(...)` are allowed to run for real: both are local,
non-network operations (verified before writing this module).

Timing is exercised with genuinely tiny `request_timeout_seconds` /
`execution_timeout_seconds` overrides (0.02-0.05s), the same technique
already used by tests/test_execution_modes.py — real `asyncio.wait_for`
timeouts fire, but in milliseconds, never the real 25s/60s.

Hanging attempts are simulated with plain `async def` stubs (not
`AsyncMock(side_effect=<coroutine>)`) because a coroutine object handed to
AsyncMock as a side_effect value is returned as-is, not awaited by the mock
machinery — a real `async def` stub avoids that ambiguity entirely.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from google.api_core.exceptions import InvalidArgument, ResourceExhausted, Unauthenticated

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.base import Provider, ProviderResult  # noqa: E402
from providers.gemini_provider import GeminiProvider  # noqa: E402
from providers.conclusion_schema import eligible_synthesis_answers  # noqa: E402


def _fake_response(text: str = "Gemini answer"):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15,
        ),
        candidates=[],
    )


def _provider(**kwargs) -> GeminiProvider:
    kwargs.setdefault("api_key", "fixture-only-key")
    kwargs.setdefault("request_timeout_seconds", 0.05)
    kwargs.setdefault("max_retries", 1)
    return GeminiProvider(**kwargs)


class QuickLiveProvider(Provider):
    """Minimal always-succeeds provider, standing in for OpenAI/Mistral."""

    def __init__(self, provider_id: str, name: str, text: str):
        self.id = provider_id
        self.label = name
        self.provider_name = name
        super().__init__(execution_timeout_seconds=5.0)
        self._text = text

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        return ProviderResult(text=self._text, model_used="mock-model", is_mock=False)


# --------------------------------------------------------------------------
# 1) First attempt succeeds -> no retry.
# --------------------------------------------------------------------------

def test_success_on_first_attempt_never_retries():
    provider = _provider()
    call_mock = AsyncMock(return_value=_fake_response("first try"))
    with patch("providers.gemini_provider._call_once", call_mock):
        result = asyncio.run(provider.timed_generate("q", "s"))

    assert result.provider_status == "LIVE"
    assert result.text == "first try"
    assert result.is_mock is False
    assert call_mock.await_count == 1


# --------------------------------------------------------------------------
# 2) Internal timeout on attempt 1, success on attempt 2 -> LIVE.
# --------------------------------------------------------------------------

def test_internal_timeout_then_success_is_live():
    provider = _provider(request_timeout_seconds=0.03, max_retries=1)
    calls: list[int] = []

    async def flaky(_gmodel, _prompt):
        calls.append(1)
        if len(calls) == 1:
            await asyncio.Event().wait()  # never resolves -> outer wait_for times out
        return _fake_response("second try")

    with patch("providers.gemini_provider._call_once", flaky):
        started = time.perf_counter()
        result = asyncio.run(provider.timed_generate("q", "s"))
        elapsed = time.perf_counter() - started

    assert elapsed < 2.0  # real but tiny timeouts, never the real 25s/60s
    assert result.provider_status == "LIVE"
    assert result.text == "second try"
    assert len(calls) == 2


# --------------------------------------------------------------------------
# 3) Transient error (HTTP 429) on attempt 1, success on attempt 2 -> LIVE.
# --------------------------------------------------------------------------

def test_transient_error_then_success_is_live():
    provider = _provider()
    call_mock = AsyncMock(
        side_effect=[ResourceExhausted("rate limited"), _fake_response("recovered")]
    )
    with patch("providers.gemini_provider._call_once", call_mock):
        result = asyncio.run(provider.timed_generate("q", "s"))

    assert result.provider_status == "LIVE"
    assert result.text == "recovered"
    assert call_mock.await_count == 2


# --------------------------------------------------------------------------
# 4) Timeout on both attempts -> FAILED (never propagates past timed_generate).
# --------------------------------------------------------------------------

def test_timeout_on_every_attempt_is_failed():
    provider = _provider(request_timeout_seconds=0.02, max_retries=1)
    calls: list[int] = []

    async def always_hang(_gmodel, _prompt):
        calls.append(1)
        await asyncio.Event().wait()

    with patch("providers.gemini_provider._call_once", always_hang):
        started = time.perf_counter()
        result = asyncio.run(provider.timed_generate("q", "s"))
        elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert result.is_mock is False
    assert len(calls) == 2  # attempt 1 + the single configured retry


# --------------------------------------------------------------------------
# 5) Permanent error -> no retry, fails immediately.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    InvalidArgument("model not found"),
    Unauthenticated("bad API key"),
])
def test_permanent_error_never_retries(exc):
    provider = _provider()
    call_mock = AsyncMock(side_effect=exc)
    with patch("providers.gemini_provider._call_once", call_mock):
        result = asyncio.run(provider.timed_generate("q", "s"))

    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert call_mock.await_count == 1  # no retry for a permanent error


# --------------------------------------------------------------------------
# 6) At most one retry, however many times it keeps failing.
# --------------------------------------------------------------------------

def test_never_exceeds_configured_max_retries():
    provider = _provider(max_retries=1)
    call_mock = AsyncMock(side_effect=ResourceExhausted("still rate limited"))
    with patch("providers.gemini_provider._call_once", call_mock):
        result = asyncio.run(provider.timed_generate("q", "s"))

    assert result.provider_status == "FAILED"
    # GEMINI_MAX_RETRIES=1 -> at most 2 total attempts, never more.
    assert call_mock.await_count == 2


def test_zero_retries_means_a_single_attempt():
    provider = _provider(max_retries=0)
    call_mock = AsyncMock(side_effect=ResourceExhausted("rate limited"))
    with patch("providers.gemini_provider._call_once", call_mock):
        result = asyncio.run(provider.timed_generate("q", "s"))

    assert result.provider_status == "FAILED"
    assert call_mock.await_count == 1


# --------------------------------------------------------------------------
# 7) Internal timeout stays below the outer (unchanged) provider timeout.
# --------------------------------------------------------------------------

def test_internal_timeout_is_configurable_and_below_default_outer_timeout():
    from providers.base import DEFAULT_PROVIDER_TIMEOUT_SECONDS

    default_provider = GeminiProvider(api_key="fixture-only-key")
    assert default_provider.request_timeout_seconds == 25.0
    assert default_provider.max_retries == 1
    # Default budget: (1 + max_retries) attempts * request_timeout, plus a
    # short backoff, must stay comfortably under the outer 60s deadline.
    worst_case = (
        default_provider.request_timeout_seconds * (default_provider.max_retries + 1)
        + 0.5
    )
    assert worst_case < DEFAULT_PROVIDER_TIMEOUT_SECONDS
    assert default_provider.execution_timeout_seconds == DEFAULT_PROVIDER_TIMEOUT_SECONDS

    custom = GeminiProvider(api_key="fixture-only-key", request_timeout_seconds=10, max_retries=2)
    assert custom.request_timeout_seconds == 10.0
    assert custom.max_retries == 2


def test_internal_timeout_configurable_via_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "3")
    provider = GeminiProvider(api_key="fixture-only-key")
    assert provider.request_timeout_seconds == 12.0
    assert provider.max_retries == 3


# --------------------------------------------------------------------------
# 8) OpenAI and Mistral are unaffected — outer timeout/execution model is
#    identical for all three; Gemini's new internal retry logic is entirely
#    self-contained in gemini_provider.py.
# --------------------------------------------------------------------------

def test_openai_and_mistral_not_affected_by_gemini_changes():
    from providers.openai_provider import OpenAIProvider
    from providers.mistral_provider import MistralProvider
    import providers.openai_provider as openai_mod
    import providers.mistral_provider as mistral_mod

    # Neither module references anything from gemini_provider.
    assert not hasattr(openai_mod, "GeminiProvider")
    assert not hasattr(mistral_mod, "GeminiProvider")

    # Their own construction/timeout defaults are untouched by this patch.
    mistral = MistralProvider(api_key="k")
    assert mistral.timeout_seconds == 45.0
    assert mistral.max_retries == 2
    openai_provider = OpenAIProvider(api_key="k")
    assert openai_provider.available is True


# --------------------------------------------------------------------------
# 9) Comparison continues correctly when Gemini fails definitively, and
#    10) no MOCK content silently replaces the failed Gemini response.
# --------------------------------------------------------------------------

def test_panel_continues_when_gemini_fails_after_retry():
    gemini = _provider(request_timeout_seconds=0.02, max_retries=1)

    async def always_hang(_gmodel, _prompt):
        await asyncio.Event().wait()

    providers = [
        QuickLiveProvider("model-a", "OpenAI", "OpenAI answer"),
        gemini,
        QuickLiveProvider("model-e", "Mistral AI", "Mistral answer"),
    ]

    async def run_panel():
        with patch("providers.gemini_provider._call_once", always_hang):
            return await asyncio.gather(
                *(provider.timed_generate("question", "system") for provider in providers)
            )

    started = time.perf_counter()
    results = asyncio.run(run_panel())
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert [r.provider_status for r in results] == ["LIVE", "FAILED", "LIVE"]
    assert results[0].text == "OpenAI answer"
    assert results[2].text == "Mistral answer"

    # No MOCK content silently replaces the failed Gemini response.
    assert results[1].text == ""
    assert results[1].is_mock is False

    synthesis_candidates = eligible_synthesis_answers(
        [
            SimpleNamespace(id=p.id, provider_status=r.provider_status, text=r.text)
            for p, r in zip(providers, results)
        ],
        "LIVE",
    )
    synthesis_ids = {c["id"] for c in synthesis_candidates}
    assert synthesis_ids == {"model-a", "model-e"}
    assert "model-c" not in synthesis_ids


# --------------------------------------------------------------------------
# Logging — attempts / retries / timeout / exhaustion are distinguishable,
# without leaking prompt or system content.
# --------------------------------------------------------------------------

def test_log_events_distinguish_attempts_retry_and_exhaustion_without_leaking_content(caplog):
    provider = _provider(request_timeout_seconds=0.02, max_retries=1)

    async def always_hang(_gmodel, _prompt):
        await asyncio.Event().wait()

    with caplog.at_level(logging.INFO):
        with patch("providers.gemini_provider._call_once", always_hang):
            asyncio.run(
                provider.timed_generate("super secret prompt", "super secret system")
            )

    text = caplog.text
    assert "gemini_attempt_started" in text
    assert "gemini_attempt_internal_timeout" in text
    assert "gemini_retry_scheduled" in text
    assert "gemini_retries_exhausted" in text
    assert "super secret prompt" not in text
    assert "super secret system" not in text


def test_transient_error_is_logged_distinctly_from_timeout(caplog):
    provider = _provider()
    call_mock = AsyncMock(
        side_effect=[ResourceExhausted("rate limited"), _fake_response("ok")]
    )
    with caplog.at_level(logging.INFO):
        with patch("providers.gemini_provider._call_once", call_mock):
            asyncio.run(provider.timed_generate("q", "s"))

    assert "gemini_transient_error" in caplog.text
    assert "gemini_attempt_internal_timeout" not in caplog.text


def test_permanent_error_is_logged_distinctly(caplog):
    provider = _provider()
    call_mock = AsyncMock(side_effect=InvalidArgument("bad model"))
    with caplog.at_level(logging.INFO):
        with patch("providers.gemini_provider._call_once", call_mock):
            asyncio.run(provider.timed_generate("q", "s"))

    assert "gemini_permanent_error" in caplog.text
    assert "gemini_retry_scheduled" not in caplog.text
