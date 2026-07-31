"""Provider registry for AI Referee.

Design goals:
    * Every implemented FREE provider is discovered from this registry and
      contributes through the same comparison and synthesis pipeline.
    * Claude is fully implemented but gated behind ENABLE_CLAUDE and the
      Premium plan. Activating Claude at platform level requires only:
        1. `ENABLE_CLAUDE=true` in backend/.env
        2. A valid `ANTHROPIC_API_KEY`
      No code change required.
    * Grok is advertised as a Coming Soon slot and cannot be invoked until
      its builder is wired.
    * BYOK: `selected_providers(user_id=..., plan=Plan.BYOK)` transparently
      overrides the platform API key with the user's encrypted key.

Adding or activating a provider only requires flipping an env flag
(ENABLE_OPENAI, ENABLE_GEMINI, ENABLE_CLAUDE, ENABLE_GROK, ENABLE_MISTRAL)
and — for real vendors — supplying the API key.

Exports:
    selected_providers(user_id=None, plan=None) -> live Provider instances.
    all_provider_specs()                        -> metadata for EVERY slot.
    provider_status()                           -> the payload for /api/providers.
    providers_for_execution(...)                -> explicit LIVE or DEMO panel.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional

from .base import Provider
from .openai_provider import OpenAIProvider
from .gemini_provider import GeminiProvider
from .mistral_provider import MistralProvider
from .anthropic_provider import AnthropicProvider
from .mock_provider import build_mock_providers
from .plans import Plan, entitlements_for
from .key_source import resolve_api_key

log = logging.getLogger(__name__)

CORE_PROVIDER_IDS = ("model-a", "model-c")


# --------------------------------------------------------------------------
# Registry — one entry per model slot the app knows about.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSpec:
    id: str                 # stable slot id (model-a, model-c, ...)
    label: str              # user-facing name (ChatGPT, Gemini, Claude, ...)
    codename: str           # user-facing model version
    provider_name: str      # vendor (OpenAI, Google DeepMind, ...)
    provider_key: str       # stable public key (openai, gemini, mistral, ...)
    enable_env: str         # env flag that turns the slot on
    key_env: str            # env var that holds the platform API key
    tier: str               # "free" | "premium"
    # Factory: takes an optional api_key override (BYOK) and returns a Provider.
    builder: Optional[Callable[[Optional[str]], Provider]]
    accent: str = ""


def _build_openai(api_key: Optional[str] = None) -> Provider:
    return OpenAIProvider(api_key=api_key)


def _build_gemini(api_key: Optional[str] = None) -> Provider:
    return GeminiProvider(api_key=api_key)


def _build_claude(api_key: Optional[str] = None) -> Provider:
    return AnthropicProvider(api_key=api_key)


def _build_mistral(api_key: Optional[str] = None) -> Provider:
    return MistralProvider(api_key=api_key)


PROVIDER_REGISTRY: list[ProviderSpec] = [
    ProviderSpec(
        id="model-a", label="ChatGPT", codename="GPT-5.4 mini",
        provider_name="OpenAI", provider_key="openai",
        enable_env="ENABLE_OPENAI", key_env="OPENAI_API_KEY",
        tier="free", builder=_build_openai, accent="#10A37F",
    ),
    ProviderSpec(
        id="model-c", label="Gemini", codename="3.5 Flash",
        provider_name="Google DeepMind", provider_key="gemini",
        enable_env="ENABLE_GEMINI", key_env="GEMINI_API_KEY",
        tier="free", builder=_build_gemini, accent="#4285F4",
    ),
    # --- Coming soon (free tier, disabled) ---
    ProviderSpec(
        id="model-d", label="Grok", codename="3.0",
        provider_name="xAI", provider_key="grok",
        enable_env="ENABLE_GROK", key_env="XAI_API_KEY",
        tier="free", builder=None, accent="#F43F5E",
    ),
    ProviderSpec(
        id="model-e", label="Mistral", codename="Mistral Small",
        provider_name="Mistral AI", provider_key="mistral",
        enable_env="ENABLE_MISTRAL", key_env="MISTRAL_API_KEY",
        tier="free", builder=_build_mistral, accent="#FF7A00",
    ),
    # --- Premium (Claude) — fully wired, disabled by default ---
    ProviderSpec(
        id="model-b", label="Claude", codename="Sonnet 4.6",
        provider_name="Anthropic", provider_key="claude",
        enable_env="ENABLE_CLAUDE", key_env="ANTHROPIC_API_KEY",
        tier="premium", builder=_build_claude, accent="#D97757",
    ),
]


# --------------------------------------------------------------------------
# Enable / status helpers
# --------------------------------------------------------------------------

def _env_true(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def _slot_enabled(spec: ProviderSpec) -> bool:
    """Core providers default on; an explicit false still disables them."""
    raw = os.environ.get(spec.enable_env)
    if raw is None:
        return spec.id in CORE_PROVIDER_IDS
    return raw.strip().lower() == "true"


def _slot_status(spec: ProviderSpec) -> str:
    """Return "live" | "coming_soon" | "premium_coming_soon".

    A slot is only LIVE when its ENABLE_X flag is true, it has a real
    builder (non-mock), and a platform API key is present. Otherwise it
    is a Coming Soon slot — never invoked by the compare engine.

    Note: BYOK bypasses this platform-level check on a per-request basis.
    """
    if spec.tier == "premium" and not _slot_enabled(spec):
        return "premium_coming_soon"
    if not _slot_enabled(spec):
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
        "mistral": "model-e",
    }
    return key_map.get(primary_provider_id(), "model-a")


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def selected_providers(
    user_id: Optional[str] = None,
    plan: Optional[Plan | str] = None,
) -> list[Provider]:
    """Provider instances that the compare endpoint may call.

    Default behaviour (no plan/user_id): current FREE-plan compatibility —
    returns only slots whose platform-level status is "live".

    When called with a plan (e.g. Plan.PREMIUM or Plan.BYOK):
      * Only slots the plan is entitled to are considered.
      * For BYOK, the user's stored key overrides the platform key.
      * A slot that has neither a user key nor a platform key is skipped.
    """
    ents = entitlements_for(plan) if (plan is not None or user_id is not None) else None
    live: list[Provider] = []
    for spec in PROVIDER_REGISTRY:
        if spec.builder is None:
            continue  # slot not wired yet (currently Grok)

        # Default path — preserves current behaviour for the compare endpoint.
        if ents is None:
            if _slot_status(spec) != "live":
                continue
            try:
                live.append(spec.builder(None))
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to build live provider %s: %s", spec.id, exc)
            continue

        # Plan-aware path.
        if spec.id not in ents.allowed_provider_ids:
            continue
        # For premium slots we still respect ENABLE_X — activation must be
        # explicit at the platform level even if the plan allows the slot.
        # For BYOK, we allow user-key-only slots (platform key optional).
        if not ents.can_use_own_keys and _slot_status(spec) != "live":
            continue

        resolved = resolve_api_key(spec.id, user_id=user_id, plan=ents.plan)
        if resolved is None:
            continue
        try:
            live.append(spec.builder(resolved.api_key))
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to build provider %s: %s", spec.id, exc)

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
            "provider_key": spec.provider_key,
            "tier": spec.tier,
            "status": status,           # live | coming_soon | premium_coming_soon
            "live": status == "live",
            "is_primary": spec.id == primary_slot and status == "live",
            "accent": spec.accent,
            "enable_env": spec.enable_env,
        })
    return out


def execution_mode() -> str:
    """Return DEMO only when the operator explicitly sets USE_MOCK=true."""
    return "DEMO" if _env_true("USE_MOCK") else "LIVE"


def providers_for_execution(
    user_id: Optional[str] = None,
    plan: Optional[Plan | str] = None,
) -> tuple[str, list[Provider]]:
    """Select real providers or the explicit demo panel, never a mixture."""
    mode = execution_mode()
    if mode == "DEMO":
        return mode, build_mock_providers()
    return mode, selected_providers(user_id=user_id, plan=plan)


def core_provider_specs() -> list[dict]:
    """Metadata for the two providers expected in the current comparison."""
    return [
        spec
        for spec in all_provider_specs()
        if spec["id"] in CORE_PROVIDER_IDS
    ]


def comparison_provider_specs() -> list[dict]:
    """Metadata for every integrated FREE comparison slot."""
    integrated_free_ids = {
        spec.id
        for spec in PROVIDER_REGISTRY
        if spec.tier == "free" and spec.builder is not None
    }
    return [
        spec
        for spec in all_provider_specs()
        if spec["id"] in integrated_free_ids
    ]


def provider_unavailable_status(provider_id: str) -> str:
    """Distinguish an intentionally disabled slot from a broken configuration."""
    spec = next((item for item in PROVIDER_REGISTRY if item.id == provider_id), None)
    if spec is None or provider_id in CORE_PROVIDER_IDS:
        return "FAILED"
    if not _slot_enabled(spec):
        return "DISABLED"
    # An enabled, integrated provider that cannot be called (for example
    # because its key is missing) is a real execution failure, not Coming Soon.
    return "FAILED"


def provider_unavailable_reason(provider_id: str) -> str:
    """Explain why a core provider could not be called, without secrets."""
    spec = next((s for s in PROVIDER_REGISTRY if s.id == provider_id), None)
    if spec is None:
        return "Provider is not registered."
    if not _slot_enabled(spec):
        return f"{spec.label} is disabled by {spec.enable_env}=false."
    if spec.builder is None:
        return f"{spec.label} integration is not available."
    if not os.environ.get(spec.key_env, "").strip():
        return f"{spec.label} API key is not configured."
    return f"{spec.label} could not be initialized."


def provider_status() -> list[dict]:
    """Backwards-compatible payload for /api/providers."""
    return all_provider_specs()


def fallback_for(provider: Provider):
    """Compatibility shim: hidden provider fallbacks are intentionally disabled."""
    return None
