"""Provider registry for AI Referee.

`selected_providers()` returns the four models that participate in every
comparison in a stable order:
  - model-a → OpenAI  (LIVE when OPENAI_API_KEY is set)
  - model-b → Claude  (mock — provider ready, not enabled)
  - model-c → Gemini  (mock by default; flip ENABLE_GEMINI=true to activate)
  - model-d → Grok    (mock — provider ready, not enabled)

`fallback_for(id)` returns the paired MockProvider that supplies the text
when a real call fails — powering the frontend FALLBACK badge.
"""
from __future__ import annotations

import os

from .base import Provider
from .openai_provider import OpenAIProvider
from .gemini_provider import GeminiProvider  # noqa: F401 — imported so the class is ready
from .mock_provider import MockProvider, build_mock_providers


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
    """Gemini is fully implemented but disabled by default.
    Enable by setting ENABLE_GEMINI=true AND GEMINI_API_KEY=... in .env.
    """
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
        # model-b — Claude (ready, not yet enabled)
        MockProvider(
            id="model-b",
            label="Claude",
            codename="Sonnet 4.6",
            provider_name="Anthropic",
            template_key="claude",
            env_var="ANTHROPIC_API_KEY",
        ),
        _gemini_or_mock(),
        # model-d — Grok (ready, not yet enabled)
        MockProvider(
            id="model-d",
            label="Grok",
            codename="3.0",
            provider_name="xAI",
            template_key="grok",
            env_var="XAI_API_KEY",
        ),
    ]


def fallback_for(provider: Provider) -> MockProvider:
    """Return a MockProvider whose `.fallback_text()` matches this provider's slot."""
    template_map = {
        "model-a": "openai",
        "model-b": "claude",
        "model-c": "gemini",
        "model-d": "grok",
    }
    return MockProvider(
        id=provider.id,
        label=provider.label,
        codename=provider.codename,
        provider_name=provider.provider_name,
        template_key=template_map.get(provider.id, "openai"),
        env_var="",
    )


def provider_status() -> list[dict]:
    """Summary used by /api/providers."""
    out: list[dict] = []
    for p in selected_providers():
        live = not isinstance(p, MockProvider) and p.available
        out.append({
            "id": p.id,
            "label": p.label,
            "codename": p.codename,
            "provider": p.provider_name,
            "live": live,
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
