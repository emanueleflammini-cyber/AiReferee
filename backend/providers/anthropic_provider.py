"""Anthropic (Claude) provider — Premium tier.

Wiring:
  * The provider is instantiated ONLY when the registry decides its slot is
    "live" (ENABLE_CLAUDE=true AND a real API key is available). When those
    conditions aren't met the compare engine never touches Claude.
  * BYOK: the constructor accepts an optional `api_key` override so a
    per-user key resolved via `providers.key_source.resolve_api_key` can
    replace the platform key transparently.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Optional

from .base import Provider, ProviderResult

log = logging.getLogger(__name__)

SYSTEM_FALLBACK = (
    "You are one participant in a multi-model AI consensus panel called AI Referee. "
    "Answer the user's question directly, precisely, and with your best reasoning. "
    "Keep the answer self-contained — the panel synthesises multiple answers afterwards."
)

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()


class AnthropicProvider(Provider):
    """Claude provider. Only used by the Premium plan (once ENABLE_CLAUDE=true)."""

    id = "model-b"
    label = "Claude"
    codename = DEFAULT_MODEL
    provider_name = "Anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None) -> None:
        super().__init__()
        self.model = model
        self.codename = model
        # BYOK: prefer explicit override, otherwise the platform key.
        self.api_key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        self.available = bool(self.api_key)
        self._client = None
        if self.available:
            try:
                from anthropic import AsyncAnthropic  # lazy import — only when live.
                self._client = AsyncAnthropic(api_key=self.api_key)
            except Exception as exc:  # noqa: BLE001
                log.warning("AnthropicProvider init failed: %s", exc)
                self.available = False
                self._client = None

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        if not self.available or self._client is None:
            raise RuntimeError("ANTHROPIC_API_KEY is missing — cannot call Claude")

        sys_msg = system or SYSTEM_FALLBACK
        start = time.perf_counter()
        try:
            resp = await self._client.messages.create(
                model=self.model,
                system=sys_msg,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:  # noqa: BLE001 — surface any SDK error to caller
            raise RuntimeError(f"Anthropic API error: {e}") from e

        latency_ms = int((time.perf_counter() - start) * 1000)
        # `resp.content` is a list of content blocks. Only text blocks are joined.
        parts = [
            getattr(b, "text", "") for b in getattr(resp, "content", [])
            if getattr(b, "type", "") == "text"
        ]
        text = "".join(parts).strip()
        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        model_used = getattr(resp, "model", self.model) or self.model

        return ProviderResult(
            text=text,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            model_used=model_used,
            is_mock=False,
        )
