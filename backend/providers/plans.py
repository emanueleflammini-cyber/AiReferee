"""Plan / entitlement definitions for AI Referee.

Three business plans are prepared here so the rest of the codebase can query
entitlements without knowing anything about billing:

  * FREE     — platform API, only enabled providers (OpenAI + Gemini), daily
               usage limits, Smart Reuse.
  * PREMIUM  — future subscription: Claude enabled, three-model consensus,
               higher limits, priority processing. Not yet activated.
  * BYOK     — future one-time purchase: users bring their own API keys.
               Requests using a user key MUST NOT consume platform credits.

Only the FREE plan is actually used today. PREMIUM and BYOK are scaffolding —
they exist so activating them will not require refactoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Plan(str, Enum):
    FREE = "free"
    PREMIUM = "premium"
    BYOK = "byok"


@dataclass(frozen=True)
class Entitlements:
    plan: Plan
    # Slot IDs the plan is allowed to invoke (subset of PROVIDER_REGISTRY).
    allowed_provider_ids: frozenset[str] = field(default_factory=frozenset)
    # Daily usage limits (used by rate-limiter — not yet enforced).
    daily_compare_limit: int = 20
    # Whether the plan can bring its own API keys.
    can_use_own_keys: bool = False
    # Priority tier (higher wins in future scheduling).
    priority: int = 0


PLAN_ENTITLEMENTS: dict[Plan, Entitlements] = {
    Plan.FREE: Entitlements(
        plan=Plan.FREE,
        allowed_provider_ids=frozenset({"model-a", "model-c"}),
        daily_compare_limit=20,
        can_use_own_keys=False,
        priority=0,
    ),
    Plan.PREMIUM: Entitlements(
        plan=Plan.PREMIUM,
        # Claude joins on Premium. Grok/Mistral remain gated by ENABLE_X flags.
        allowed_provider_ids=frozenset({"model-a", "model-b", "model-c", "model-d", "model-e"}),
        daily_compare_limit=200,
        can_use_own_keys=False,
        priority=10,
    ),
    Plan.BYOK: Entitlements(
        plan=Plan.BYOK,
        # BYOK users can invoke any slot they hold a key for.
        allowed_provider_ids=frozenset({"model-a", "model-b", "model-c", "model-d", "model-e"}),
        daily_compare_limit=10_000,  # effectively unlimited — throttling relies on user's own quotas
        can_use_own_keys=True,
        priority=5,
    ),
}


def entitlements_for(plan: Plan | str | None) -> Entitlements:
    """Resolve entitlements for a plan. Unknown or None -> FREE."""
    if plan is None:
        return PLAN_ENTITLEMENTS[Plan.FREE]
    try:
        p = plan if isinstance(plan, Plan) else Plan(plan)
    except ValueError:
        return PLAN_ENTITLEMENTS[Plan.FREE]
    return PLAN_ENTITLEMENTS.get(p, PLAN_ENTITLEMENTS[Plan.FREE])
