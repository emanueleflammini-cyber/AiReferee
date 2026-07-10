"""Trusted Conclusion synthesis in the caller's language.

Takes the individual model responses returned by the compare engine and
produces a single synthesised "Trusted Conclusion" in `target_lang`. The
synthesis prompt is language-aware: the model is instructed to write the
final answer entirely in the requested language, regardless of the
language of the source responses.

Uses the same OpenAI SDK / model family as the OpenAIProvider — no new
provider dependency.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Iterable, Optional

from openai import AsyncOpenAI

from .base import estimate_cost
from .translator import LANG_NAMES

log = logging.getLogger(__name__)

SYNTH_MODEL = os.environ.get("SYNTH_MODEL", "gpt-5.4-mini").strip()


class Synthesizer:
    """Produce a Trusted Conclusion + translate reused conclusions."""

    def __init__(self) -> None:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.available = bool(key)
        self._client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=key) if key else None

    async def synthesize(
        self,
        prompt: str,
        answers: Iterable[dict],
        target_lang: str,
        audience: str = "professional",
        fmt: str = "paragraph",
    ) -> dict:
        """Return {text, input_tokens, output_tokens, latency_ms, cost_usd, model_used, language}."""
        if not self._client:
            raise RuntimeError("OPENAI_API_KEY missing — cannot synthesise Trusted Conclusion")

        target_name = LANG_NAMES.get(target_lang, "English")
        # Filter out failed / empty answers so the model has real signal to work with.
        clean = [a for a in answers if (a.get("text") or "").strip()]
        if not clean:
            return {
                "text": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 0,
                "cost_usd": 0.0,
                "model_used": SYNTH_MODEL,
                "language": target_lang,
            }

        panel_block = "\n\n".join(
            f"### {a.get('label') or a.get('id')} ({a.get('provider','?')})\n{a['text'].strip()}"
            for a in clean
        )

        system = (
            "You are AI Referee's Consensus Engine. You have received the answers of a panel "
            "of independent frontier AI models to the same user question. Your job is to synthesise "
            "ONE 'Trusted Conclusion' that represents what these answers agree on, resolves obvious "
            "disagreements with the most defensible reasoning, and cites nothing that is not in the "
            "source answers.\n\n"
            f"Audience: {audience}. Preferred format: {fmt}.\n\n"
            f"WRITE THE FINAL CONCLUSION ENTIRELY IN {target_name}. Do not include the original "
            "question, do not list the models, do not add preambles like 'The Trusted Conclusion is'. "
            "Return ONLY the synthesised answer body."
        )
        user_msg = (
            f"User question:\n{prompt}\n\n"
            f"Panel responses:\n{panel_block}\n\n"
            f"Now write the Trusted Conclusion in {target_name}."
        )

        start = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(
                model=SYNTH_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.3,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Synthesizer OpenAI call failed: %s", exc)
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)
        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        model_used = getattr(resp, "model", SYNTH_MODEL) or SYNTH_MODEL
        return {
            "text": text,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "latency_ms": latency_ms,
            "cost_usd": estimate_cost(model_used, in_tok, out_tok),
            "model_used": model_used,
            "language": target_lang,
        }
