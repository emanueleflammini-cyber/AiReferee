"""Mock providers — used when the corresponding API key isn't configured yet.

Every real provider (Anthropic/Claude, Google/Gemini, xAI/Grok, Mistral,
DeepSeek) has a mock counterpart with the same `id`. This lets AI Referee
run a full 4-model comparison as soon as OPENAI_API_KEY is set — the
other three slots return realistic placeholder text tagged `is_mock=True`
until you add their keys.
"""
from __future__ import annotations

import asyncio
import os
import random

from .base import Provider, ProviderResult


DEFAULT_MOCK_TEMPLATES: dict[str, str] = {
    "claude": (
        "Here's how I'd frame the question:\n\n"
        "{q}\n\n"
        "The strongest defensible answer starts by naming the assumptions, then walks through the reasoning "
        "step by step. Where the evidence is thin, I flag it explicitly rather than smoothing it over — "
        "Referee will surface those caveats in the Trusted Conclusion."
    ),
    "gemini": (
        "Answer to: \"{q}\"\n\n"
        "Three axes matter here — mechanics, tradeoffs, and how the choice interacts with the "
        "environment. Once we split the problem along those axes, most disagreements between models "
        "collapse into 'which axis you optimise for'."
    ),
    "grok": (
        "Short version on \"{q}\":\n\n"
        "Skip the theory, name the failure modes. Every good answer to this kind of question earns its "
        "confidence by predicting where the naive approach breaks — not by restating the textbook."
    ),
    "mistral": (
        "On \"{q}\": most of the value is in what you *don't* say. A concise answer that names the "
        "one non-obvious constraint beats a comprehensive answer that lists ten obvious ones."
    ),
    "deepseek": (
        "For \"{q}\": think in terms of information gain per token. A distributed answer with clear "
        "structure — definition, constraints, tradeoffs, edge cases — scores higher on Referee's "
        "evidence meter than a long free-form response."
    ),
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
        # A mock provider is "available" only in the sense that it always
        # returns something — but we still expose whether the real key is
        # configured so the caller can prefer a real provider when possible.
        self.real_key_configured = bool(os.environ.get(env_var, "").strip())
        self.available = True

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        await asyncio.sleep(random.uniform(0.6, 1.6))  # simulate network latency
        template = DEFAULT_MOCK_TEMPLATES.get(self._template_key, "Placeholder answer for: {q}")
        text = template.format(q=prompt.strip())
        return ProviderResult(
            text=text,
            latency_ms=int(random.uniform(700, 1400)),
            tokens=len(text) // 4,
            is_mock=True,
        )


def build_mock_providers() -> list[Provider]:
    return [
        MockProvider(
            id="model-b",
            label="Claude",
            codename="Sonnet 4.6",
            provider_name="Anthropic",
            template_key="claude",
            env_var="ANTHROPIC_API_KEY",
        ),
        MockProvider(
            id="model-c",
            label="Gemini",
            codename="3.1 Pro",
            provider_name="Google DeepMind",
            template_key="gemini",
            env_var="GEMINI_API_KEY",
        ),
        MockProvider(
            id="model-d",
            label="Grok",
            codename="3.0",
            provider_name="xAI",
            template_key="grok",
            env_var="XAI_API_KEY",
        ),
    ]
