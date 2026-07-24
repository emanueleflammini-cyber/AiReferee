"""Phase 1 safety tests for explicit LIVE / FAILED / MOCK execution."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.base import Provider, ProviderResult  # noqa: E402
from providers.mock_provider import build_mock_providers  # noqa: E402
from providers.registry import execution_mode, providers_for_execution  # noqa: E402


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


def test_demo_panel_contains_only_current_mock_slots(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "true")
    mode, providers = providers_for_execution()
    assert mode == "DEMO"
    assert [provider.id for provider in providers] == ["model-a", "model-c"]

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
    mode, providers = providers_for_execution()
    assert mode == "LIVE"
    assert providers == []


def test_openai_disabled_keeps_only_gemini(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("ENABLE_OPENAI", "false")
    monkeypatch.setenv("ENABLE_GEMINI", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    mode, providers = providers_for_execution()
    assert mode == "LIVE"
    assert [provider.id for provider in providers] == ["model-c"]


def test_gemini_disabled_keeps_only_openai(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("ENABLE_OPENAI", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ENABLE_GEMINI", "false")
    mode, providers = providers_for_execution()
    assert mode == "LIVE"
    assert [provider.id for provider in providers] == ["model-a"]


def test_mock_utility_remains_available_for_tests():
    assert len(build_mock_providers()) == 2
