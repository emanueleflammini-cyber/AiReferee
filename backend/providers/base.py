"""Provider abstraction layer for AI Referee.

Every model that participates in a Referee comparison implements the
`Provider` interface — one `generate()` call returns text + full usage stats.
`timed_generate()` wraps `generate()`, records latency, and gracefully falls
back to a caller-supplied mock text if the real provider raises. The mock
fallback is what powers the "FALLBACK" badge on the frontend.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable


# --- Pricing (USD per 1M tokens) --------------------------------------------
# Best-effort estimates; treat all values as advisory until you replace them
# with the vendor's live rate card. Cost is always labelled "estimated" in the
# UI so users know it isn't authoritative.
PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-5.5-mini": {"input": 0.15, "output": 0.60},
    "gpt-5.5":      {"input": 2.50, "output": 10.00},
    "gpt-5.4":      {"input": 1.50, "output": 6.00},
    "gpt-5.4-mini": {"input": 0.15, "output": 0.60},
    # Google
    "gemini-3.1-pro-preview": {"input": 1.25, "output": 5.00},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro":         {"input": 1.25, "output": 5.00},
    "gemini-2.5-flash":       {"input": 0.30, "output": 2.50},
    "gemini-2.0-flash":       {"input": 0.10, "output": 0.40},
    # Anthropic
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    # xAI
    "grok-3": {"input": 2.00, "output": 10.00},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD estimate for a single call. Zero for unknown models.

    OpenAI (and other vendors) often echo back a versioned model string like
    `gpt-5.4-mini-2026-03-17`. We first try an exact match, then fall back to
    matching by longest known prefix so the versioned form still gets priced.
    """
    if not model:
        return 0.0
    p = PRICING.get(model)
    if not p:
        # Longest-prefix match — pick the most specific pricing entry that starts with `model`.
        candidate = ""
        for key in PRICING:
            if model.startswith(key) and len(key) > len(candidate):
                candidate = key
        if candidate:
            p = PRICING[candidate]
    if not p:
        return 0.0
    return round(
        (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"],
        6,
    )


@dataclass
class ProviderResult:
    text: str
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model_used: str = ""            # exact model string echoed by the vendor
    is_mock: bool = False
    error: Optional[str] = None     # populated when a real call failed and we fell back

    def with_computed_cost(self) -> "ProviderResult":
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens
        if self.cost_usd == 0.0 and self.model_used:
            self.cost_usd = estimate_cost(self.model_used, self.input_tokens, self.output_tokens)
        return self


class Provider(ABC):
    """Base class for every LLM provider."""

    id: str = ""
    label: str = ""
    codename: str = ""
    provider_name: str = ""

    def __init__(self) -> None:
        self.available: bool = False

    @abstractmethod
    async def generate(self, prompt: str, system: str) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError

    async def timed_generate(
        self,
        prompt: str,
        system: str,
        fallback_text_fn: Optional[Callable[[str], Awaitable[ProviderResult]]] = None,
    ) -> ProviderResult:
        """Run the provider. On any exception, call `fallback_text_fn` (which
        returns a mock ProviderResult) and mark the result with the original
        error so the UI can surface a FALLBACK badge.
        """
        start = time.perf_counter()
        try:
            res = await self.generate(prompt, system)
            if res.latency_ms <= 0:
                res.latency_ms = int((time.perf_counter() - start) * 1000)
            return res.with_computed_cost()
        except Exception as exc:  # noqa: BLE001 — surface any error to caller
            elapsed = int((time.perf_counter() - start) * 1000)
            err_msg = f"{type(exc).__name__}: {exc}"
            if fallback_text_fn:
                fb = await fallback_text_fn(prompt)
                fb.latency_ms = fb.latency_ms or elapsed
                fb.is_mock = True
                fb.error = err_msg
                return fb.with_computed_cost()
            return ProviderResult(
                text="",
                latency_ms=elapsed,
                is_mock=True,
                error=err_msg,
            )
