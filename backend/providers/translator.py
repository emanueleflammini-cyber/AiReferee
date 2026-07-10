"""On-demand translation for user-facing Trusted Conclusions.

Uses OpenAI `gpt-5.4-mini` (~$0.15/1M in, $0.60/1M out) via the same official
SDK the OpenAIProvider uses. Only translates the final conclusion body —
never the individual model responses or logs.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from openai import AsyncOpenAI

from .base import estimate_cost

TRANSLATE_MODEL = "gpt-5.4-mini"

LANG_NAMES = {
    "en": "English", "it": "Italian", "es": "Spanish",
    "fr": "French", "de": "German", "pt": "Portuguese",
}


class Translator:
    def __init__(self) -> None:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.available = bool(key)
        self._client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=key) if key else None

    async def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> dict:
        """Return {text, input_tokens, output_tokens, latency_ms, cost_usd, model_used}."""
        if not self._client:
            raise RuntimeError("OPENAI_API_KEY missing — cannot translate")
        target_name = LANG_NAMES.get(target_lang, target_lang)
        source_name = LANG_NAMES.get(source_lang, source_lang) if source_lang != "auto" else "the source language"
        system = (
            f"You are a professional translator. Translate the user's message from {source_name} into {target_name}. "
            "Preserve formatting (paragraphs, lists, bold markers like **word**, numbers). "
            "Return ONLY the translated text — no preamble, no explanation."
        )
        start = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=TRANSLATE_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        out = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        model_used = getattr(resp, "model", TRANSLATE_MODEL) or TRANSLATE_MODEL
        return {
            "text": out,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "latency_ms": latency_ms,
            "cost_usd": estimate_cost(model_used, in_tok, out_tok),
            "model_used": model_used,
        }
