"""Unit tests for the real Mistral REST provider."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.mistral_provider import MistralProvider  # noqa: E402
from providers.base import Provider, ProviderResult  # noqa: E402
from providers.registry import providers_for_execution  # noqa: E402


def _success_transport(captured: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "mistral-small-latest",
                "choices": [
                    {"message": {"role": "assistant", "content": "Mistral answer"}}
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "total_tokens": 19,
                },
            },
        )

    return httpx.MockTransport(handler)


def test_mistral_success_uses_official_contract():
    captured: dict = {}
    provider = MistralProvider(
        api_key="test-mistral-key",
        max_retries=0,
        transport=_success_transport(captured),
    )

    result = asyncio.run(provider.timed_generate("question", "system"))

    assert result.provider_status == "LIVE"
    assert result.text == "Mistral answer"
    assert result.model_used == "mistral-small-latest"
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert result.total_tokens == 19
    assert result.cost_usd == 0.000006
    assert captured["authorization"] == "Bearer test-mistral-key"
    assert captured["payload"]["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "question"},
    ]


def test_mistral_auth_failure_is_failed_without_fake_text():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"message": "unauthorized"})
    )
    provider = MistralProvider(
        api_key="invalid-key",
        max_retries=0,
        transport=transport,
    )

    result = asyncio.run(provider.timed_generate("question", "system"))

    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert "MISTRAL_API_KEY" in (result.error or "")
    assert "invalid-key" not in (result.error or "")


def test_mistral_timeout_has_explicit_status():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = MistralProvider(
        api_key="test-key",
        timeout_seconds=0.01,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(provider.timed_generate("question", "system"))

    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert "timeout" in (result.error or "").lower()


def test_mistral_missing_key_is_failed_without_fake_text(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    provider = MistralProvider(api_key="", max_retries=0)

    result = asyncio.run(provider.timed_generate("question", "system"))

    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert result.cost_usd == 0.0
    assert "MISTRAL_API_KEY" in (result.error or "")


def test_mistral_upstream_failure_is_isolated():
    provider = MistralProvider(
        api_key="test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"message": "unavailable"})
        ),
    )

    result = asyncio.run(provider.timed_generate("question", "system"))

    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert result.cost_usd == 0.0
    assert "HTTP 503" in (result.error or "")


def test_mistral_malformed_json_is_failed_without_fake_text():
    provider = MistralProvider(
        api_key="test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"{not-valid-json",
                headers={"content-type": "application/json"},
            )
        ),
    )

    result = asyncio.run(provider.timed_generate("question", "system"))

    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert result.cost_usd == 0.0


def test_mistral_empty_response_is_failed_and_usage_is_not_billed():
    provider = MistralProvider(
        api_key="test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "mistral-small-latest",
                    "choices": [{"message": {"content": ""}}],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 0,
                        "total_tokens": 100,
                    },
                },
            )
        ),
    )

    result = asyncio.run(provider.timed_generate("question", "system"))

    assert result.provider_status == "FAILED"
    assert result.text == ""
    assert result.cost_usd == 0.0


def test_mistral_continues_when_another_provider_fails():
    class FailingProvider(Provider):
        async def generate(self, prompt: str, system: str) -> ProviderResult:
            raise RuntimeError("older provider unavailable")

    mistral = MistralProvider(
        api_key="test-key",
        max_retries=0,
        transport=_success_transport({}),
    )

    async def run_panel():
        return await asyncio.gather(
            FailingProvider().timed_generate("question", "system"),
            mistral.timed_generate("question", "system"),
        )

    failed, succeeded = asyncio.run(run_panel())
    assert failed.provider_status == "FAILED"
    assert succeeded.provider_status == "LIVE"
    assert succeeded.text == "Mistral answer"


def test_registry_selects_mistral_only_when_enabled_with_key(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("ENABLE_OPENAI", "false")
    monkeypatch.setenv("ENABLE_GEMINI", "false")
    monkeypatch.setenv("ENABLE_MISTRAL", "true")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")

    mode, providers = providers_for_execution()

    assert mode == "LIVE"
    assert [provider.id for provider in providers] == ["model-e"]
    assert providers[0].provider_name == "Mistral AI"


def test_registry_does_not_select_mistral_without_key(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("ENABLE_OPENAI", "false")
    monkeypatch.setenv("ENABLE_GEMINI", "false")
    monkeypatch.setenv("ENABLE_MISTRAL", "true")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    mode, providers = providers_for_execution()

    assert mode == "LIVE"
    assert providers == []
