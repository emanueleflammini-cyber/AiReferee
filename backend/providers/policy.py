"""Slow Provider Tolerance Policy — configuration foundation only.

This module defines the *shape* of the future early-synthesis quorum policy
(minimum live responses, core-provider requirement, grace window,
disagreement threshold, late-arriving behaviour) plus a per-provider policy
(core/eligible-for-quorum/late-result-allowed/priority). It is disconnected
from the runtime on purpose: `server.py` does not import this module, and
`compare_query`'s `asyncio.gather` call is unchanged by it. Every value
below is inert configuration until a later patch wires an orchestrator to
read it.

Building this now, separately from the runtime wiring, lets the eventual
early-synthesis patch be a small, reviewable diff against an
already-tested configuration surface, instead of inventing the schema and
the orchestration logic in the same change.

Extending to a new provider (Claude, Grok, DeepSeek, ...) means adding one
entry to DEFAULT_PROVIDER_POLICIES — never an `if provider_id == "..."`
branch in the orchestrator. Any provider id not listed there falls back to
DEFAULT_PROVIDER_POLICY (non-core, eligible for quorum, late results
allowed) via `get_provider_policy()`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


# --------------------------------------------------------------------------
# Per-provider policy
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderPolicy:
    """Slow-provider-tolerance policy for one provider slot.

    Nothing reads this yet (see module docstring).

    - core_provider: mirrors the existing, already-shipped notion of a
      "core" provider (see server.py CORE_PROVIDER_IDS) — a slot the
      product always expects to be present, not a new concept.
    - eligible_for_quorum: whether this provider may count toward the
      future minimum-live-responses quorum at all.
    - late_result_allowed: whether a result arriving after synthesis has
      already started may still be used (for cache/telemetry/optional
      refresh) rather than discarded outright.
    - priority: relative weight for future tie-breaking (e.g. which
      provider to prefer keeping in a partial panel); higher is more
      important. Not read anywhere yet.
    - grace_window_override_seconds / timeout_policy_ref: named
      placeholders for a future per-provider override of the global grace
      window / timeout policy. `None` means "use the global default" —
      there is no global default consumer yet either.
    """

    provider_id: str
    enabled: bool = True
    core_provider: bool = False
    eligible_for_quorum: bool = True
    late_result_allowed: bool = True
    priority: int = 0
    grace_window_override_seconds: Optional[float] = None
    timeout_policy_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.provider_id or not self.provider_id.strip():
            raise ValueError("ProviderPolicy.provider_id must be a non-empty string")
        if self.priority < 0:
            raise ValueError("ProviderPolicy.priority must be >= 0")
        if (
            self.grace_window_override_seconds is not None
            and self.grace_window_override_seconds < 0
        ):
            raise ValueError(
                "ProviderPolicy.grace_window_override_seconds must be >= 0 when set"
            )


# Initial configuration. OpenAI and Gemini start as core, matching the
# existing CORE_PROVIDER_IDS = ("model-a", "model-c") notion already shipped
# in server.py — this does not introduce a new classification, it makes the
# existing one configurable for the future orchestrator. Mistral starts
# non-core. Claude/Grok/DeepSeek are not integrated yet, so they are not
# listed here at all — see get_provider_policy() below for how a future
# provider is handled without any code change.
DEFAULT_PROVIDER_POLICIES: dict[str, ProviderPolicy] = {
    "model-a": ProviderPolicy(provider_id="model-a", core_provider=True, priority=10),   # OpenAI
    "model-c": ProviderPolicy(provider_id="model-c", core_provider=True, priority=10),   # Gemini
    "model-e": ProviderPolicy(provider_id="model-e", core_provider=False, priority=5),   # Mistral
}

# Fallback for any provider id not explicitly listed above. Safe-by-default:
# non-core, eligible for quorum, late results allowed, lowest priority. This
# is what keeps the design provider-agnostic — a future integration (Claude,
# Grok, DeepSeek, ...) is usable by the future orchestrator immediately,
# with an explicit override addable later if it should become core.
DEFAULT_PROVIDER_POLICY = ProviderPolicy(provider_id="*", core_provider=False, priority=0)


def get_provider_policy(provider_id: str) -> ProviderPolicy:
    """Return the configured policy for `provider_id`, or the safe default."""
    return DEFAULT_PROVIDER_POLICIES.get(provider_id, DEFAULT_PROVIDER_POLICY)


# --------------------------------------------------------------------------
# Quorum policy — schema + defaults only. Nothing reads this yet.
# --------------------------------------------------------------------------

# Every late-arriving-result strategy considered for the future
# orchestrator: "ignore" it entirely, keep it for "telemetry_only", let it
# "auto_update" an already-shown answer (deliberately the riskiest — product
# has flagged that an answer must never change while the user is reading
# it), the recommended default "cache_and_notify" (persist for Smart Reuse
# + an opt-in "an answer arrived, refresh?" affordance, never automatic),
# or "cache_only_for_future" (persist only, no in-session affordance at
# all). late_arriving_behavior is a plain string tag, not a Python enum, on
# purpose — the future orchestrator interprets it; this module only
# validates it is one of these known values so a typo fails loudly instead
# of silently doing nothing.
LATE_ARRIVING_BEHAVIORS = frozenset({
    "ignore",
    "telemetry_only",
    "auto_update",
    "cache_and_notify",
    "cache_only_for_future",
})


#: Upper bound for disagreement_wait_seconds (fix/early-synthesis-
#: disagreement-bounded-wait). The whole point of this policy is to put a
#: ceiling well below a slow provider's own timeout (production: Gemini's
#: two attempts took ~50.9s) on how long the disagreement gate may hold up
#: an already-numerically-satisfied quorum — an unbounded or very large
#: value would silently recreate the original problem this policy exists
#: to fix. 30s is comfortably below any observed provider timeout while
#: still generous enough to let a genuinely slow-but-useful third provider
#: help resolve the disagreement.
MAX_DISAGREEMENT_WAIT_SECONDS = 30.0


@dataclass(frozen=True)
class QuorumPolicy:
    """Future early-synthesis decision policy. Schema + defaults only.

    disagreement_threshold is a placeholder for the future reuse of the
    existing Jaccard/token similarity heuristic already used by Smart Reuse
    (see server.py: `jaccard()` / `tokens_of()`) to decide whether two early
    responses disagree too much to synthesize without the rest of the
    panel. This module does not call that heuristic and does not duplicate
    it — it only reserves the threshold value it would eventually be
    compared against.

    disagreement_wait_seconds (fix/early-synthesis-disagreement-bounded-
    wait) is distinct from grace_window_seconds: grace_window_seconds is
    the extra wait applied AFTER a full (raw + disagreement-gate-passed)
    semantic quorum is already reached, to let a close-behind provider join
    in. disagreement_wait_seconds is the separate, bounded wait applied
    when the RAW quorum (minimum_live_responses + core requirement) is
    already satisfied but the disagreement gate blocks it — giving the
    still-pending provider(s) a capped chance to arrive and help resolve
    the disagreement before proceeding with the LIVE responses already in
    hand. Default 6.0s is sized directly off the production incident this
    policy fixes (query_id 0f07deb2-...): OpenAI LIVE at 3.9s, Mistral LIVE
    at 11.25s, disagreement gate failed, Gemini did not finish until ~50.9s
    later — a 6s disagreement wait would have let synthesis start at
    roughly 11.25 + 6 ≈ 17s instead of waiting the full ~50.9s.
    """

    minimum_live_responses: int = 2
    require_core_provider: bool = True
    grace_window_seconds: float = 4.0
    disagreement_threshold: float = 0.35
    late_arriving_behavior: str = "cache_and_notify"
    disagreement_wait_seconds: float = 6.0

    def __post_init__(self) -> None:
        if self.minimum_live_responses < 1:
            raise ValueError("QuorumPolicy.minimum_live_responses must be >= 1")
        if self.grace_window_seconds < 0:
            raise ValueError("QuorumPolicy.grace_window_seconds must be >= 0")
        if not (0.0 <= self.disagreement_threshold <= 1.0):
            raise ValueError(
                "QuorumPolicy.disagreement_threshold must be within [0.0, 1.0]"
            )
        if self.late_arriving_behavior not in LATE_ARRIVING_BEHAVIORS:
            raise ValueError(
                f"Unsupported late_arriving_behavior '{self.late_arriving_behavior}'. "
                f"Supported values: {sorted(LATE_ARRIVING_BEHAVIORS)}."
            )
        if not (0.0 <= self.disagreement_wait_seconds <= MAX_DISAGREEMENT_WAIT_SECONDS):
            raise ValueError(
                "QuorumPolicy.disagreement_wait_seconds must be within "
                f"[0.0, {MAX_DISAGREEMENT_WAIT_SECONDS}]"
            )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def build_quorum_policy_from_env() -> QuorumPolicy:
    """Build a QuorumPolicy from defaults, optionally overridden via env.

    Configurable now so a future orchestrator patch can tune these values
    without a code change — consistent with how every other cross-cutting
    limit in this codebase is configured (MAX_PROMPT_LENGTH, provider
    timeouts, ...). An invalid override (e.g. an out-of-range threshold)
    still raises via QuorumPolicy.__post_init__ — configuration errors fail
    loudly rather than silently falling back. Not read by compare_query yet.
    """
    return QuorumPolicy(
        minimum_live_responses=_env_int(
            "QUORUM_MIN_LIVE_RESPONSES", QuorumPolicy.minimum_live_responses
        ),
        require_core_provider=_env_bool(
            "QUORUM_REQUIRE_CORE_PROVIDER", QuorumPolicy.require_core_provider
        ),
        grace_window_seconds=_env_float(
            "QUORUM_GRACE_WINDOW_SECONDS", QuorumPolicy.grace_window_seconds
        ),
        disagreement_threshold=_env_float(
            "QUORUM_DISAGREEMENT_THRESHOLD", QuorumPolicy.disagreement_threshold
        ),
        late_arriving_behavior=(
            os.environ.get("QUORUM_LATE_ARRIVING_BEHAVIOR", "").strip()
            or QuorumPolicy.late_arriving_behavior
        ),
        disagreement_wait_seconds=_env_float(
            "QUORUM_DISAGREEMENT_WAIT_SECONDS", QuorumPolicy.disagreement_wait_seconds
        ),
    )


# Precomputed default, mirroring the pattern of other module-level constants
# in this codebase (e.g. MAX_PROMPT_LENGTH in server.py). Safe to evaluate
# at import time: nothing imports this module yet, so an invalid override in
# a deployment's environment cannot affect server startup.
DEFAULT_QUORUM_POLICY: QuorumPolicy = build_quorum_policy_from_env()
