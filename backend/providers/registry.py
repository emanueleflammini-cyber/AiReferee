"""Provider registry for AI Referee.

Design goals (Feb 2026):
    * OpenAI + Gemini are the only providers that ever get called from the
      compare endpoint. They contribute equally to the Trusted Conclusion.
    * Claude, Grok and Mistral are configured in the registry so the UI can
      advertise them, but they must never be invoked while their ENABLE_X
      flag is false. Their `status` field tells the frontend how to label
      them ("live" / "coming_soon" / "premium_coming_soon").
    * Adding or activating a provider only requires flipping an env flag
      (ENABLE_OPENAI, ENABLE_GEMINI, ENABLE_CLAUDE, ENABLE_GROK,
      ENABLE_MISTRAL) and — for real vendors — supplying the API key.

Exports:
    selected_providers()        -> live Provider instances the compare
                                    endpoint should iterate over.
    all_provider_specs()        -> metadata for EVERY registered slot
                                    (live + coming_soon + premium_coming_soon).
    provider_status()           -> the payload for /api/providers.
    fallback_for(provider)      -> async fallback callable for LIVE providers.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from .base import Provider, ProviderResult
from .openai_provider import OpenAIProvider, SYSTEM_FALLBACK
from .gemini_provider import GeminiProvider

log = logging.getLogger(__name__)

FallbackFn = Callable[[str], Awaitable[ProviderResult]]


# --------------------------------------------------------------------------
# Registry — one entry per model slot the app knows about.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSpec:
    id: str                 # stable slot id (model-a, model-c, ...)
    label: str              # user-facing name (ChatGPT, Gemini, Claude, ...)
    codename: str           # user-facing model version
    provider_name: str      # vendor (OpenAI, Google DeepMind, ...)
    enable_env: str         # env flag that turns the slot on
    key_env: str            # env var that holds the API key (may be empty)
    tier: str               # "free" | "premium"
    builder: Optional[Callable[[], Provider]]  # factory when the slot goes live
    accent: str = ""        # brand color hint for the frontend


def _build_openai() -> Provider:
    return OpenAIProvider()


def _build_gemini() -> Provider:
    return GeminiProvider()


PROVIDER_REGISTRY: list[ProviderSpec] = [
    ProviderSpec(
        id="model-a", label="ChatGPT", codename="GPT-5.4 mini",
        provider_name="OpenAI",
        enable_env="ENABLE_OPENAI", key_env="OPENAI_API_KEY",
        tier="free", builder=_build_openai, accent="#10A37F",
    ),
    ProviderSpec(
        id="model-c", label="Gemini", codename="3.1 Pro",
        provider_name="Google DeepMind",
        enable_env="ENABLE_GEMINI", key_env="GEMINI_API_KEY",
        tier="free", builder=_build_gemini, accent="#4285F4",
    ),
    # --- Coming soon (free tier, disabled) ---
    ProviderSpec(
        id="model-d", label="Grok", codename="3.0",
        provider_name="xAI",
        enable_env="ENABLE_GROK", key_env="XAI_API_KEY",
        tier="free", builder=None, accent="#F43F5E",
    ),
    ProviderSpec(
        id="model-e", label="Mistral", codename="Large 2",
        provider_name="Mistral AI",
        enable_env="ENABLE_MISTRAL", key_env="MISTRAL_API_KEY",
        tier="free", builder=None, accent="#FF7A00",
    ),
    # --- Premium (Claude) — coming soon ---
    ProviderSpec(
        id="model-b", label="Claude", codename="Sonnet 4.6",
        provider_name="Anthropic",
        enable_env="ENABLE_CLAUDE", key_env="ANTHROPIC_API_KEY",
        tier="premium", builder=None, accent="#D97757",
    ),
]


# --------------------------------------------------------------------------
# Enable / status helpers
# --------------------------------------------------------------------------

def _env_true(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def _slot_status(spec: ProviderSpec) -> str:
    """Return "live" | "coming_soon" | "premium_coming_soon".

    A slot is only LIVE when its ENABLE_X flag is true, it has a real
    builder (non-mock), and an API key is present. Otherwise it is a
    Coming Soon slot — never invoked by the compare engine.
    """
    if spec.tier == "premium" and not _env_true(spec.enable_env):
        return "premium_coming_soon"
    if not _env_true(spec.enable_env):
        return "coming_soon"
    if spec.builder is None:
        return "coming_soon"
    if not os.environ.get(spec.key_env, "").strip():
        # Enabled but missing key — surface as coming_soon so we don't call it.
        return "coming_soon"
    return "live"


def primary_provider_id() -> str:
    return os.environ.get("PRIMARY_PROVIDER", "gemini").strip().lower()


def _primary_slot_id() -> str:
    key_map = {
        "openai": "model-a",
        "gemini": "model-c", "google": "model-c",
    }
    return key_map.get(primary_provider_id(), "model-a")


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def selected_providers() -> list[Provider]:
    """Provider instances that the compare endpoint may call.

    Disabled slots (coming_soon / premium_coming_soon) are omitted — the
    backend never calls them.
    """
    live: list[Provider] = []
    for spec in PROVIDER_REGISTRY:
        if _slot_status(spec) != "live":
            continue
        assert spec.builder is not None  # narrow for mypy — status "live" guarantees builder
        try:
            live.append(spec.builder())
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to build live provider %s: %s", spec.id, exc)
    return live


def all_provider_specs() -> list[dict]:
    """Full slot list (including disabled) with status metadata for the UI."""
    primary_slot = _primary_slot_id()
    out: list[dict] = []
    for spec in PROVIDER_REGISTRY:
        status = _slot_status(spec)
        out.append({
            "id": spec.id,
            "label": spec.label,
            "codename": spec.codename,
            "provider": spec.provider_name,
            "tier": spec.tier,
            "status": status,           # live | coming_soon | premium_coming_soon
            "live": status == "live",
            "is_primary": spec.id == primary_slot and status == "live",
            "accent": spec.accent,
            "enable_env": spec.enable_env,
        })
    return out


def provider_status() -> list[dict]:
    """Backwards-compatible payload for /api/providers."""
    return all_provider_specs()


# --------------------------------------------------------------------------
# Fallback chain — only ever installed on LIVE providers.
# --------------------------------------------------------------------------

def _openai_rescue_fn() -> FallbackFn:
    """If a live provider fails, try OpenAI once, then give up (raise)."""
    async def _fn(prompt: str) -> ProviderResult:
        openai = OpenAIProvider()
        if openai.available:
            res = await openai.generate(prompt, SYSTEM_FALLBACK)
            res.is_mock = True
            res.error = "Primary provider failed — served by OpenAI rescue path"
            return res.with_computed_cost()
        # If OpenAI itself isn't available, propagate an explicit error result.
        return ProviderResult(
            text="",
            is_mock=True,
            error="No live fallback available.",
        )
    return _fn


def fallback_for(provider: Provider) -> Optional[FallbackFn]:
    """Return a fallback callable ONLY for the Gemini slot (rescued by OpenAI).

    OpenAI is the last line — its failure is surfaced directly to the caller
    so we never fake a live answer. Disabled slots don't have a fallback
    because they are never invoked.
    """
    if isinstance(provider, GeminiProvider):
        return _openai_rescue_fn()
    return None
