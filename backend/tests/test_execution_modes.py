"""Phase 1 safety tests for explicit LIVE / FAILED / MOCK execution."""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.base import (  # noqa: E402
    Provider,
    ProviderResult,
    billable_provider_cost,
)
from providers.conclusion_schema import (  # noqa: E402
    eligible_synthesis_answers,
)
from providers.gemini_provider import GeminiProvider  # noqa: E402
from providers.mock_provider import build_mock_providers  # noqa: E402
from providers.registry import (  # noqa: E402
    execution_mode,
    provider_unavailable_status,
    providers_for_execution,
)


class SuccessfulProvider(Provider):
    id = "success"

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        return ProviderResult(text="real answer", model_used="test-live")


class FailingProvider(Provider):
    id = "failure"

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        raise RuntimeError("provider unavailable")


class QuickLiveProvider(Provider):
    def __init__(self, provider_id: str, provider_name: str, text: str):
        self.id = provider_id
        self.provider_name = provider_name
        self._text = text
        super().__init__(execution_timeout_seconds=0.1)

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        return ProviderResult(text=self._text, model_used="test-live")


def test_use_mock_requires_explicit_true(monkeypatch):
    monkeypatch.delenv("USE_MOCK", raising=False)
    assert execution_mode() == "LIVE"

    monkeypatch.setenv("USE_MOCK", "false")
    assert execution_mode() == "LIVE"

    monkeypatch.setenv("USE_MOCK", "true")
    assert execution_mode() == "DEMO"


def test_demo_panel_contains_only_integrated_mock_slots(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "true")
    mode, providers = providers_for_execution()
    assert mode == "DEMO"
    assert [provider.id for provider in providers] == ["model-a", "model-c", "model-e"]

    results = [
        asyncio.run(provider.timed_generate("question", "system"))
        for provider in providers
    ]
    assert all(result.provider_status == "MOCK" for result in results)
    assert all(result.is_mock for result in results)
    assert all(result.text for result in results)


def test_live_success_is_explicit():
    result = asyncio.run(
        SuccessfulProvider().timed_generate("question", "system")
    )
    assert result.provider_status == "LIVE"
    assert result.is_mock is False
    assert result.text == "real answer"


def test_live_failure_has_no_replacement_text():
    result = asyncio.run(
        FailingProvider().timed_generate("question", "system")
    )
    assert result.provider_status == "FAILED"
    assert result.is_mock is False
    assert result.text == ""
    assert "provider unavailable" in (result.error or "")


def test_failure_error_redacts_configured_keys(monkeypatch):
    secret = "secret-key-that-must-not-leak"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    class LeakyProvider(Provider):
        async def generate(self, prompt: str, system: str) -> ProviderResult:
            raise RuntimeError(f"request failed for {secret}")

    result = asyncio.run(LeakyProvider().timed_generate("q", "s"))
    assert secret not in (result.error or "")
    assert "[REDACTED]" in (result.error or "")


def test_mock_builders_are_not_selected_when_flag_is_false(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("ENABLE_OPENAI", "false")
    monkeypatch.setenv("ENABLE_GEMINI", "false")
    monkeypatch.setenv("ENABLE_MISTRAL", "false")
    mode, providers = providers_for_execution()
    assert mode == "LIVE"
    assert providers == []


def test_openai_disabled_keeps_only_gemini(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("ENABLE_OPENAI", "false")
    monkeypatch.setenv("ENABLE_GEMINI", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("ENABLE_MISTRAL", "false")
    mode, providers = providers_for_execution()
    assert mode == "LIVE"
    assert [provider.id for provider in providers] == ["model-c"]


def test_gemini_disabled_keeps_only_openai(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("ENABLE_OPENAI", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ENABLE_GEMINI", "false")
    monkeypatch.setenv("ENABLE_MISTRAL", "false")
    mode, providers = providers_for_execution()
    assert mode == "LIVE"
    assert [provider.id for provider in providers] == ["model-a"]


def test_mock_utility_remains_available_for_tests():
    assert len(build_mock_providers()) == 3


def test_failed_and_empty_provider_results_never_add_cost():
    failed = ProviderResult(
        text="stale text",
        provider_status="FAILED",
        cost_usd=1.25,
    )
    empty_live = ProviderResult(
        text="",
        provider_status="LIVE",
        cost_usd=1.25,
    )
    live = ProviderResult(
        text="usable evidence",
        provider_status="LIVE",
        cost_usd=0.125,
    )

    assert billable_provider_cost(failed, failed.provider_status) == 0.0
    assert billable_provider_cost(empty_live, empty_live.provider_status) == 0.0
    assert billable_provider_cost(live, live.provider_status) == 0.125


def test_enabled_mistral_missing_key_is_failed_but_disabled_is_explicit(
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_MISTRAL", "true")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert provider_unavailable_status("model-e") == "FAILED"

    monkeypatch.setenv("ENABLE_MISTRAL", "false")
    assert provider_unavailable_status("model-e") == "DISABLED"


def test_provider_that_never_finishes_is_bounded_and_logged(caplog):
    class HangingProvider(Provider):
        id = "model-c"
        label = "Gemini"
        provider_name = "Google DeepMind"

        def __init__(self):
            super().__init__(execution_timeout_seconds=0.02)

        async def generate(self, prompt: str, system: str) -> ProviderResult:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    started = time.perf_counter()
    with caplog.at_level(logging.INFO):
        result = asyncio.run(
            HangingProvider().timed_generate(
                "sensitive prompt",
                "sensitive system",
            )
        )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert result.is_mock is False
    assert result.error == "Provider request timed out after 0.02 seconds."
    assert "provider_started" in caplog.text
    assert "provider_timeout" in caplog.text
    assert "sensitive prompt" not in caplog.text
    assert "sensitive system" not in caplog.text


def test_gemini_uses_its_independent_timeout_without_api_call(
    monkeypatch,
):
    monkeypatch.setenv("PROVIDER_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("GEMINI_PROVIDER_TIMEOUT_SECONDS", "0.02")
    provider = GeminiProvider(api_key="fixture-only-key")

    async def never_returns(prompt: str, system: str) -> ProviderResult:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(provider, "generate", never_returns)
    result = asyncio.run(provider.timed_generate("question", "system"))

    assert provider.execution_timeout_seconds == 0.02
    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert result.is_mock is False


def test_openai_and_mistral_complete_when_gemini_times_out():
    class HangingGemini(Provider):
        id = "model-c"
        label = "Gemini"
        provider_name = "Google DeepMind"

        def __init__(self):
            super().__init__(execution_timeout_seconds=0.02)

        async def generate(self, prompt: str, system: str) -> ProviderResult:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    providers = [
        QuickLiveProvider("model-a", "OpenAI", "OpenAI answer"),
        HangingGemini(),
        QuickLiveProvider("model-e", "Mistral AI", "Mistral answer"),
    ]

    async def run_panel():
        return await asyncio.gather(
            *(
                provider.timed_generate("question", "system")
                for provider in providers
            )
        )

    started = time.perf_counter()
    results = asyncio.run(run_panel())
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert [result.provider_status for result in results] == [
        "LIVE",
        "FAILED",
        "LIVE",
    ]
    assert results[1].text == ""
    assert results[1].is_mock is False

    synthesis_candidates = eligible_synthesis_answers(
        [
            {
                "id": provider.id,
                "provider_response_id": provider.id,
                "provider_key": {
                    "model-a": "openai",
                    "model-c": "gemini",
                    "model-e": "mistral",
                }[provider.id],
                "provider_status": result.provider_status,
                "execution_mode": "LIVE",
                "text": result.text,
            }
            for provider, result in zip(providers, results)
        ],
        "LIVE",
    )
    assert [item["provider_key"] for item in synthesis_candidates] == [
        "openai",
        "mistral",
    ]


def test_provider_lifecycle_logs_never_include_request_content(caplog):
    with caplog.at_level(logging.INFO):
        success = asyncio.run(
            SuccessfulProvider().timed_generate(
                "private success prompt",
                "private success system",
            )
        )
        failed = asyncio.run(
            FailingProvider().timed_generate(
                "private failure prompt",
                "private failure system",
            )
        )

    assert success.provider_status == "LIVE"
    assert failed.provider_status == "FAILED"
    assert "provider_started" in caplog.text
    assert "provider_completed" in caplog.text
    assert "provider_failed" in caplog.text
    assert "private success prompt" not in caplog.text
    assert "private success system" not in caplog.text
    assert "private failure prompt" not in caplog.text
    assert "private failure system" not in caplog.text
