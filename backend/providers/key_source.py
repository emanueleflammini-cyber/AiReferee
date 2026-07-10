"""Key source abstraction for AI Referee.

Resolves the API key to use for a given provider slot and (optional) user.

Precedence for BYOK-eligible plans:
    1. User-owned key (encrypted at rest, decrypted on demand).
    2. Platform environment key (for slots enabled at the platform level).
    3. None — the provider is not callable.

For FREE and PREMIUM plans, only the platform key is consulted. The user_id
argument is ignored to guarantee we never mix billing tiers by accident.

This module NEVER logs raw API keys — helper `_redact()` is used everywhere.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from .plans import Plan, entitlements_for

log = logging.getLogger(__name__)


# Provider slot -> environment variable name for the platform key.
PLATFORM_KEY_ENV: dict[str, str] = {
    "model-a": "OPENAI_API_KEY",
    "model-c": "GEMINI_API_KEY",
    "model-b": "ANTHROPIC_API_KEY",
    "model-d": "XAI_API_KEY",
    "model-e": "MISTRAL_API_KEY",
}


@dataclass(frozen=True)
class ResolvedKey:
    provider_id: str
    api_key: str
    source: str          # "user" | "platform"
    plan: Plan


def _redact(key: str) -> str:
    if not key:
        return "<empty>"
    if len(key) <= 8:
        return "<redacted>"
    return f"{key[:4]}…{key[-4:]}"


def _user_key_lookup(user_id: str, provider_id: str) -> Optional[str]:
    """Fetch a user-owned decrypted key. Returns None if no key is set.

    Delegated to `services.user_keys` so this module has no Mongo dependency.
    Imported lazily to keep the import graph shallow and testable.
    """
    try:
        from services.user_keys import get_decrypted_user_key
    except Exception as exc:  # noqa: BLE001
        log.debug("user_keys service unavailable: %s", exc)
        return None
    return get_decrypted_user_key(user_id, provider_id)


def resolve_api_key(
    provider_id: str,
    *,
    user_id: Optional[str] = None,
    plan: Optional[Plan | str] = None,
) -> Optional[ResolvedKey]:
    """Resolve which API key should be used for `provider_id`.

    Returns None when neither a user key nor a platform key exists.
    The caller is responsible for skipping the provider when the result
    is None. This function NEVER raises on missing keys.
    """
    ents = entitlements_for(plan)

    # 1) BYOK — only for plans that allow user keys.
    if ents.can_use_own_keys and user_id:
        user_key = _user_key_lookup(user_id, provider_id)
        if user_key:
            log.info(
                "resolve_api_key: using USER key for %s (plan=%s, user=%s, key=%s)",
                provider_id, ents.plan.value, user_id, _redact(user_key),
            )
            return ResolvedKey(provider_id=provider_id, api_key=user_key,
                               source="user", plan=ents.plan)

    # 2) Platform key (only for slots the plan is allowed to invoke).
    if provider_id not in ents.allowed_provider_ids:
        return None
    env_var = PLATFORM_KEY_ENV.get(provider_id)
    if not env_var:
        return None
    platform_key = os.environ.get(env_var, "").strip()
    if platform_key:
        return ResolvedKey(provider_id=provider_id, api_key=platform_key,
                           source="platform", plan=ents.plan)

    return None
