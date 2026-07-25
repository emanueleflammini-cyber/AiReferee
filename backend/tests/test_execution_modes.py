"""Phase 1 safety tests for explicit LIVE / FAILED / MOCK execution."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.base import (  # noqa: E402
    Provider,
    ProviderResult,
    billable_provider_cost,
)
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
