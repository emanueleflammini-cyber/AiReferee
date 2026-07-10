"""Provider registry for AI Referee.

`selected_providers()` returns the four models that participate in every
comparison in a stable order:
  - model-a → OpenAI  (LIVE when OPENAI_API_KEY is set)
  - model-b → Claude  (mock — provider ready, not enabled)
  - model-c → Gemini  (LIVE when GEMINI_API_KEY + ENABLE_GEMINI=true)
  - model-d → Grok    (mock — provider ready, not enabled)

`primary_provider_id()` returns the id of the featured "default" provider —
its slot is the one users see as the app's primary answer generator. The
frontend gets it via /api/providers.

`fallback_for(provider)` returns an async callable that produces a
ProviderResult when the primary call fails. Gemini's fallback chains
OpenAI → mock text; every other provider falls back to themed mock text.
"""
from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable

from .base import Provider, ProviderResult
from .openai_provider import OpenAIProvider, SYSTEM_FALLBACK
from .gemini_provider import GeminiProvider  # noqa: F401 — imported so the class is ready
from .mock_provider import MockProvider, build_mock_providers  # noqa: F401

log = logging.getLogger(__name__)

FallbackFn = Callable[[str], Awaitable[ProviderResult]]


def primary_provider_id() -> str:
    return os.environ.get("PRIMARY_PROVIDER", "openai").strip().lower()


def _openai_or_mock() -> Provider:
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return OpenAIProvider()
    return MockProvider(
        id="model-a",
        label="ChatGPT",
        codename="GPT-5.4 mini",
        provider_name="OpenAI",
        template_key="openai",
        env_var="OPENAI_API_KEY",
    )


def _gemini_or_mock() -> Provider:
    enabled = os.environ.get("ENABLE_GEMINI", "false").strip().lower() == "true"
    has_key = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    if enabled and has_key:
        return GeminiProvider()
    return MockProvider(
        id="model-c",
        label="Gemini",
        codename="3.1 Pro",
        provider_name="Google DeepMind",
        template_key="gemini",
        env_var="GEMINI_API_KEY",
    )


def selected_providers() -> list[Provider]:
    return [
        _openai_or_mock(),
        # model-b — Claude (mock until wired)
        MockProvider(
            id="model-b",
            label="Claude",
            codename="Sonnet 4.6",
            provider_name="Anthropic",
            template_key="claude",
            env_var="ANTHROPIC_API_KEY",
        ),
        _gemini_or_mock(),
        # model-d — Grok (mock until wired)
        MockProvider(
            id="model-d",
            label="Grok",
            codename="3.0",
            provider_name="xAI",
            template_key="grok",
            env_var="XAI_API_KEY",
        ),
    ]


# --------------------------------------------------------------------------
# Fallback chains
# --------------------------------------------------------------------------

def _mock_fn(provider: Provider, template_key: str) -> FallbackFn:
    """Return an async callable that emits themed mock text as the fallback."""
    mock = MockProvider(
        id=provider.id,
        label=provider.label,
        codename=provider.codename,
        provider_name=provider.provider_name,
        template_key=template_key,
        env_var="",
    )

    async def _fn(prompt: str) -> ProviderResult:
        return await mock.fallback_text(prompt)

    return _fn


def _gemini_fallback_chain(gemini_provider: Provider) -> FallbackFn:
    """When Gemini fails, first try OpenAI; if OpenAI also fails, mock text."""
    themed_mock = _mock_fn(gemini_provider, "gemini")

    async def _fn(prompt: str) -> ProviderResult:
        openai = OpenAIProvider()
        if openai.available:
            try:
                res = await openai.generate(prompt, SYSTEM_FALLBACK)
                # Mark as a fallback path — same slot label (Gemini), model_used = actual OpenAI model
                res.is_mock = True
                res.error = "Gemini call failed — served by OpenAI fallback"
                return res.with_computed_cost()
            except Exception as e:  # noqa: BLE001
                log.warning("Gemini→OpenAI fallback also failed: %s", e)
        return await themed_mock(prompt)

    return _fn


def fallback_for(provider: Provider) -> FallbackFn:
    template_map = {
        "model-a": "openai",
        "model-b": "claude",
        "model-c": "gemini",
        "model-d": "grok",
    }
    # Gemini gets the OpenAI-first fallback chain
    if provider.id == "model-c" and isinstance(provider, GeminiProvider):
        return _gemini_fallback_chain(provider)
    return _mock_fn(provider, template_map.get(provider.id, "openai"))


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

def provider_status() -> list[dict]:
    primary = primary_provider_id()
    provider_key_map = {
        "openai": "model-a",
        "claude": "model-b",
        "anthropic": "model-b",
        "gemini": "model-c",
        "google": "model-c",
        "grok": "model-d",
        "xai": "model-d",
    }
    primary_slot = provider_key_map.get(primary, "model-a")
    out: list[dict] = []
    for p in selected_providers():
        live = not isinstance(p, MockProvider) and p.available
        out.append({
            "id": p.id,
            "label": p.label,
            "codename": p.codename,
            "provider": p.provider_name,
            "live": live,
            "is_primary": p.id == primary_slot,
            "fallback": "openai" if p.id == "model-c" else "mock",
            "enabled_hint": _enable_hint(p),
        })
    return out


def _enable_hint(p: Provider) -> str:
    if not isinstance(p, MockProvider):
        return ""
    if p.id == "model-a":
        return "Set OPENAI_API_KEY in backend/.env to go LIVE."
    if p.id == "model-b":
        return "Set ANTHROPIC_API_KEY (Claude ready, not yet wired to the registry)."
    if p.id == "model-c":
        return "Set GEMINI_API_KEY and ENABLE_GEMINI=true in backend/.env."
    if p.id == "model-d":
        return "Set XAI_API_KEY (Grok ready, not yet wired to the registry)."
    return ""
