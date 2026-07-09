"""Real OpenAI provider — uses the user-supplied OPENAI_API_KEY.

Talks to OpenAI through the `emergentintegrations` wrapper so we get the
same code path we'll use for Anthropic / Gemini once those keys are added.
"""
from __future__ import annotations

import os
import time
import uuid

from emergentintegrations.llm.chat import LlmChat, UserMessage

from .base import Provider, ProviderResult

SYSTEM_FALLBACK = (
    "You are one participant in a multi-model AI consensus panel called AI Referee. "
    "Answer the user's question directly, precisely, and with your best reasoning. "
    "Keep the answer self-contained — the panel synthesises multiple answers afterwards."
)


class OpenAIProvider(Provider):
    id = "model-a"
    label = "ChatGPT"
    codename = "GPT-5.5 mini"
    provider_name = "OpenAI"

    def __init__(self, model: str = "gpt-5.5-mini") -> None:
        super().__init__()
        self.model = model
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.available = bool(self.api_key)

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        if not self.available:
            raise RuntimeError("OPENAI_API_KEY is missing — cannot call OpenAI")

        sys_msg = system or SYSTEM_FALLBACK
        chat = LlmChat(
            api_key=self.api_key,
            session_id=f"referee-{uuid.uuid4()}",
            system_message=sys_msg,
        ).with_model("openai", self.model)

        start = time.perf_counter()
        response = await chat.send_message(UserMessage(text=prompt))
        latency_ms = int((time.perf_counter() - start) * 1000)

        text = response if isinstance(response, str) else str(response)
        # Approximate token count (LlmChat wrapper doesn't expose usage cleanly)
        approx_tokens = max(1, len(text) // 4)
        return ProviderResult(
            text=text.strip(),
            latency_ms=latency_ms,
            tokens=approx_tokens,
            is_mock=False,
        )
