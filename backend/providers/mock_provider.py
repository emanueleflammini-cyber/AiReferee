"""Explicit demo providers for AI Referee.

These classes are retained as test/demo utilities. Production execution may
invoke them only when ``USE_MOCK=true``. They are never provider fallbacks.
"""
from __future__ import annotations

import asyncio
import os
import random

from .base import Provider, ProviderResult


DEFAULT_MOCK_TEMPLATES: dict[str, str] = {
    "openai": (
        'Placeholder answer for: "{q}"\n\n'
        "A defensible response starts by naming the assumptions, then walks "
        "through the reasoning step by step. Referee surfaces caveats instead "
        "of smoothing them over."
    ),
    "gemini": (
        'Answer to: "{q}"\n\n'
        "Three axes matter here: mechanics, tradeoffs, and how the choice "
        "interacts with the environment. Splitting the problem along those "
        "axes makes the disagreements easier to inspect."
    ),
    # Retained for isolated provider tests and future demo panels.
    "claude": 'Demo Claude answer for: "{q}"',
    "grok": 'Demo Grok answer for: "{q}"',
    "mistral": 'Demo Mistral answer for: "{q}"',
    "deepseek": 'Demo DeepSeek answer for: "{q}"',
}


class MockProvider(Provider):
    def __init__(
        self,
        *,
        id: str,
        label: str,
        codename: str,
        provider_name: str,
        template_key: str,
        env_var: str,
    ) -> None:
        super().__init__()
        self.id = id
        self.label = label
        self.codename = codename
        self.provider_name = provider_name
        self._template_key = template_key
        self._env_var = env_var
        self.real_key_configured = bool(os.environ.get(env_var, "").strip())
        self.available = True

    def _render(self, prompt: str) -> str:
        template = DEFAULT_MOCK_TEMPLATES.get(
            self._template_key,
            "Placeholder answer for: {q}",
        )
        return template.format(q=prompt.strip())

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        await asyncio.sleep(random.uniform(0.05, 0.15))
        text = self._render(prompt)
        approx_in = max(1, len(prompt) // 4)
        approx_out = max(1, len(text) // 4)
        return ProviderResult(
            text=text,
            latency_ms=int(random.uniform(70, 140)),
            input_tokens=approx_in,
            output_tokens=approx_out,
            total_tokens=approx_in + approx_out,
            model_used="mock",
            is_mock=True,
            provider_status="MOCK",
        )

    async def fallback_text(self, prompt: str) -> ProviderResult:
        """Legacy test helper; production code never calls this method."""
        text = self._render(prompt)
        approx_in = max(1, len(prompt) // 4)
        approx_out = max(1, len(text) // 4)
        return ProviderResult(
            text=text,
            input_tokens=approx_in,
            output_tokens=approx_out,
            total_tokens=approx_in + approx_out,
            model_used="mock-test-helper",
            is_mock=True,
            provider_status="MOCK",
        )


def build_mock_providers() -> list[Provider]:
    """Build the two providers in the current explicit demo panel."""
    return [
        MockProvider(
            id="model-a",
            label="ChatGPT",
            codename="GPT-5.4 mini (Demo)",
            provider_name="OpenAI",
            template_key="openai",
            env_var="OPENAI_API_KEY",
        ),
        MockProvider(
            id="model-c",
            label="Gemini",
            codename="3.1 Pro (Demo)",
            provider_name="Google DeepMind",
            template_key="gemini",
            env_var="GEMINI_API_KEY",
        ),
    ]
