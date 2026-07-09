"""Provider abstraction layer for AI Referee.

Every model that participates in a Referee comparison implements the
`Provider` interface — one `generate()` call returns text + usage stats.
This keeps the higher-level `compare_query()` logic identical whether the
model runs locally, calls OpenAI, Anthropic, Google, xAI, Mistral or
DeepSeek. Add a new provider by subclassing `Provider` and registering it
in `providers/registry.py`.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderResult:
    text: str
    latency_ms: int
    tokens: int
    is_mock: bool = False
    error: Optional[str] = None


class Provider(ABC):
    """Base class for every LLM provider."""

    #: stable id — also used as the frontend "model-a"/"model-b"/... slot
    id: str = ""
    #: display label (e.g. "ChatGPT")
    label: str = ""
    #: model codename shown in the UI (e.g. "GPT-5.5 mini")
    codename: str = ""
    #: which vendor this hits (e.g. "OpenAI", "Google DeepMind")
    provider_name: str = ""

    def __init__(self) -> None:
        self.available: bool = False  # set true in subclass constructor

    @abstractmethod
    async def generate(self, prompt: str, system: str) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError

    async def timed_generate(self, prompt: str, system: str) -> ProviderResult:
        start = time.perf_counter()
        try:
            res = await self.generate(prompt, system)
        except Exception as exc:  # noqa: BLE001 — surface any error to caller
            elapsed = int((time.perf_counter() - start) * 1000)
            return ProviderResult(text="", latency_ms=elapsed, tokens=0, is_mock=True, error=str(exc))
        # ensure latency populated even if provider forgot
        if res.latency_ms <= 0:
            res.latency_ms = int((time.perf_counter() - start) * 1000)
        return res
