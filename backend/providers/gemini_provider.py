"""Google Gemini provider — fully implemented but disabled by default.

Enable this provider once the OpenAI slot is verified in production:

  1. Paste `GEMINI_API_KEY=...` into /app/backend/.env
  2. Set `ENABLE_GEMINI=true` (also in .env) OR flip the flag in
     `providers/registry.py`.
  3. `sudo supervisorctl restart backend`.

Uses the official `google-generativeai` SDK.
"""
from __future__ import annotations

import os
import time
import logging

from .base import Provider, ProviderResult

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-pro-preview"

SYSTEM_FALLBACK = (
    "You are one participant in a multi-model AI consensus panel called AI Referee. "
    "Answer the user's question directly, precisely, and with your best reasoning. "
    "Keep the answer self-contained — the panel synthesises multiple answers afterwards."
)


class GeminiProvider(Provider):
    id = "model-c"
    label = "Gemini"
    codename = DEFAULT_MODEL
    provider_name = "Google DeepMind"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        super().__init__()
        self.model = model
        self.codename = model
        # BYOK: prefer explicit override, otherwise the platform key.
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.available = bool(self.api_key)

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        if not self.available:
            raise RuntimeError("GEMINI_API_KEY is missing — cannot call Gemini")

        # Lazy-import so the module doesn't crash the server when the SDK isn't installed.
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "google-generativeai SDK is not installed. Run: pip install google-generativeai"
            ) from e

        genai.configure(api_key=self.api_key)
        sys_msg = system or SYSTEM_FALLBACK
        gmodel = genai.GenerativeModel(self.model, system_instruction=sys_msg)

        start = time.perf_counter()
        # The SDK's async surface — falls back to sync if unavailable.
        try:
            resp = await gmodel.generate_content_async(prompt)  # type: ignore[attr-defined]
        except AttributeError:
            resp = gmodel.generate_content(prompt)
        latency_ms = int((time.perf_counter() - start) * 1000)

        text = (getattr(resp, "text", "") or "").strip()
        usage = getattr(resp, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        total_tokens = int(getattr(usage, "total_token_count", 0) or (input_tokens + output_tokens)) if usage else 0

        return ProviderResult(
            text=text,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            model_used=self.model,
            is_mock=False,
        )
