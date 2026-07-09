"""Provider registry for AI Referee.

`selected_providers()` returns the four models that participate in each
comparison in a stable order: `model-a` (OpenAI/ChatGPT), `model-b`
(Claude), `model-c` (Gemini), `model-d` (Grok). Any provider without a
configured API key falls back to its `MockProvider` counterpart.
"""
from __future__ import annotations

import os

from .base import Provider
from .openai_provider import OpenAIProvider
from .mock_provider import MockProvider, build_mock_providers


def _openai_or_mock() -> Provider:
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return OpenAIProvider()
    return MockProvider(
        id="model-a",
        label="ChatGPT",
        codename="GPT-5.5 mini",
        provider_name="OpenAI",
        template_key="claude",  # neutral template for the mock case
        env_var="OPENAI_API_KEY",
    )


def selected_providers() -> list[Provider]:
    """Return the 4 providers that participate in the current comparison."""
    providers: list[Provider] = [_openai_or_mock(), *build_mock_providers()]
    return providers


def provider_status() -> list[dict]:
    """Small summary used by `/api/providers` for the frontend."""
    out: list[dict] = []
    for p in selected_providers():
        real = not getattr(p, "is_mock", False) and not isinstance(p, MockProvider)
        if isinstance(p, MockProvider):
            real = False
        out.append({
            "id": p.id,
            "label": p.label,
            "codename": p.codename,
            "provider": p.provider_name,
            "live": real and p.available,
        })
    return out
