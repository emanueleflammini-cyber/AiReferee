"""Real OpenAI provider — uses the user-supplied OPENAI_API_KEY.

Uses the official `openai` Python SDK directly so we can extract exact
input / output token counts from `usage`, the exact `model` string echoed by
the API, and a per-call cost estimate via `providers.base.estimate_cost`.
"""
from __future__ import annotations

import os
import time
import logging

from openai import AsyncOpenAI, APIError, AuthenticationError, RateLimitError

from .base import Provider, ProviderResult

log = logging.getLogger(__name__)

SYSTEM_FALLBACK = (
    "You are one participant in a multi-model AI consensus panel called AI Referee. "
    "Answer the user's question directly, precisely, and with your best reasoning. "
    "Keep the answer self-contained — the panel synthesises multiple answers afterwards."
)

DEFAULT_MODEL = "gpt-5.4-mini"


class OpenAIProvider(Provider):
    id = "model-a"
    label = "ChatGPT"
    codename = DEFAULT_MODEL
    provider_name = "OpenAI"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        super().__init__()
        self.model = model
        self.codename = model
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.available = bool(self.api_key)
        self._client: AsyncOpenAI | None = None
        if self.available:
            self._client = AsyncOpenAI(api_key=self.api_key)

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        if not self.available or self._client is None:
            raise RuntimeError("OPENAI_API_KEY is missing — cannot call OpenAI")

        sys_msg = system or SYSTEM_FALLBACK
        start = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt},
                ],
            )
        except AuthenticationError as e:
            raise RuntimeError(f"OpenAI auth failed — check OPENAI_API_KEY. ({e})") from e
        except RateLimitError as e:
            raise RuntimeError(f"OpenAI rate limit / quota exceeded. ({e})") from e
        except APIError as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

        latency_ms = int((time.perf_counter() - start) * 1000)
        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens))
        model_used = getattr(resp, "model", self.model) or self.model

        return ProviderResult(
            text=text,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            model_used=model_used,
            is_mock=False,
        )
