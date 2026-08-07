"""Early Synthesis — Patch 1: PENDING state + provider policy foundation.

Offline tests, no real API calls. This patch is deliberately inert: it adds
a PENDING provider-status marker (providers/base.py) and a Slow Provider
Tolerance Policy schema (providers/policy.py — ProviderPolicy, QuorumPolicy)
with no orchestrator wired to either yet. compare_query's asyncio.gather
call, its all-or-nothing wait, and the LIVE/FAILED/MOCK contract are all
unchanged.

These tests exist to prove two things:
1. The new pieces (PENDING, ProviderPolicy, QuorumPolicy) behave correctly
   in isolation — valid values accepted, invalid values rejected loudly.
2. The *existing* comparison pipeline is provably unaffected: PENDING never
   appears in a real timed_generate() result, asyncio.gather's 3-fast /
   2-live-1-failed behaviour is unchanged, and the functions that decide
   what reaches the synthesizer (eligible_synthesis_answers,
   validate_claim_analysis) already reject/exclude PENDING with zero code
   change — this patch does not touch either function.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.base import (  # noqa: E402
    FINALIZED_PROVIDER_STATUSES,
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_LIVE,
    PROVIDER_STATUS_MOCK,
    PROVIDER_STATUS_PENDING,
    PROVIDER_STATUSES,
    Provider,
    ProviderResult,
    is_pending_status,
    make_pending_result,
)
from providers.conclusion_schema import eligible_synthesis_answers  # noqa: E402
from providers.traceability_schema import validate_claim_analysis  # noqa: E402
from providers.policy import (  # noqa: E402
    DEFAULT_PROVIDER_POLICIES,
    DEFAULT_PROVIDER_POLICY,
    DEFAULT_QUORUM_POLICY,
    LATE_ARRIVING_BEHAVIORS,
    ProviderPolicy,
    QuorumPolicy,
    build_quorum_policy_from_env,
    get_provider_policy,
)


# --------------------------------------------------------------------------
# 1-4) PENDING is a valid, distinct, content-free status.
# --------------------------------------------------------------------------

class TestPendingStatus:
    def test_pending_is_a_recognized_status(self):
        assert PROVIDER_STATUS_PENDING == "PENDING"
        assert PROVIDER_STATUS_PENDING in PROVIDER_STATUSES

    def test_pending_is_not_finalized(self):
        assert PROVIDER_STATUS_PENDING not in FINALIZED_PROVIDER_STATUSES
        for finished in (PROVIDER_STATUS_LIVE, PROVIDER_STATUS_FAILED, PROVIDER_STATUS_MOCK):
            assert finished in FINALIZED_PROVIDER_STATUSES

    def test_is_pending_status_helper(self):
        assert is_pending_status("PENDING") is True
        assert is_pending_status("LIVE") is False
        assert is_pending_status("FAILED") is False
        assert is_pending_status("MOCK") is False
        assert is_pending_status("") is False

    def test_pending_never_equals_live_or_failed(self):
        # Direct, literal guard against the two explicit requirements:
        # PENDING must never be interpreted as LIVE, and never as FAILED.
        assert PROVIDER_STATUS_PENDING != PROVIDER_STATUS_LIVE
        assert PROVIDER_STATUS_PENDING != PROVIDER_STATUS_FAILED

    def test_make_pending_result_carries_no_synthetic_content(self):
        result = make_pending_result()
        assert result.provider_status == PROVIDER_STATUS_PENDING
        assert result.text == ""
        assert result.is_mock is False
        assert result.cost_usd == 0.0

    def test_pending_result_is_a_normal_provider_result(self):
        # No schema change was needed: ProviderResult.provider_status was
        # already an unconstrained str.
        result = ProviderResult(text="", provider_status=PROVIDER_STATUS_PENDING)
        assert isinstance(result, ProviderResult)
        assert result.provider_status == "PENDING"


# --------------------------------------------------------------------------
# 5) Provider policy — core / non-core configuration.
# --------------------------------------------------------------------------

class TestProviderPolicyConfiguration:
    def test_openai_and_gemini_are_core(self):
        assert DEFAULT_PROVIDER_POLICIES["model-a"].core_provider is True   # OpenAI
        assert DEFAULT_PROVIDER_POLICIES["model-c"].core_provider is True   # Gemini

    def test_mistral_is_not_core(self):
        assert DEFAULT_PROVIDER_POLICIES["model-e"].core_provider is False

    def test_all_default_policies_enabled_and_quorum_eligible(self):
        for policy in DEFAULT_PROVIDER_POLICIES.values():
            assert policy.enabled is True
            assert policy.eligible_for_quorum is True
            assert policy.late_result_allowed is True

    def test_unknown_future_provider_falls_back_to_safe_default(self):
        # Claude / Grok / DeepSeek / anything not yet integrated: no code
        # change required, no KeyError, no accidental "core" promotion.
        for future_id in ("model-b", "model-grok", "model-deepseek", "anything-else"):
            policy = get_provider_policy(future_id)
            assert policy.core_provider is False
            assert policy.eligible_for_quorum is True
            assert policy.late_result_allowed is True

    def test_get_provider_policy_returns_configured_entry_when_present(self):
        assert get_provider_policy("model-a") is DEFAULT_PROVIDER_POLICIES["model-a"]

    def test_default_provider_policy_itself_is_valid(self):
        assert DEFAULT_PROVIDER_POLICY.core_provider is False
        assert DEFAULT_PROVIDER_POLICY.priority == 0


# --------------------------------------------------------------------------
# 6-7) Quorum policy — loaded correctly, invalid values rejected.
# --------------------------------------------------------------------------

class TestQuorumPolicy:
    def test_documented_defaults(self):
        policy = QuorumPolicy()
        assert policy.minimum_live_responses == 2
        assert policy.require_core_provider is True
        assert policy.grace_window_seconds == 4.0

    def test_default_quorum_policy_singleton_is_valid(self):
        # Whatever the ambient environment happened to be at import time,
        # the precomputed singleton must still be a well-formed policy
        # (construction would have raised otherwise).
        assert isinstance(DEFAULT_QUORUM_POLICY, QuorumPolicy)
        assert DEFAULT_QUORUM_POLICY.minimum_live_responses >= 1

    def test_env_overrides_are_applied(self, monkeypatch):
        monkeypatch.setenv("QUORUM_MIN_LIVE_RESPONSES", "3")
        monkeypatch.setenv("QUORUM_REQUIRE_CORE_PROVIDER", "false")
        monkeypatch.setenv("QUORUM_GRACE_WINDOW_SECONDS", "7.5")
        monkeypatch.setenv("QUORUM_DISAGREEMENT_THRESHOLD", "0.6")
        monkeypatch.setenv("QUORUM_LATE_ARRIVING_BEHAVIOR", "telemetry_only")

        policy = build_quorum_policy_from_env()

        assert policy.minimum_live_responses == 3
        assert policy.require_core_provider is False
        assert policy.grace_window_seconds == 7.5
        assert policy.disagreement_threshold == 0.6
        assert policy.late_arriving_behavior == "telemetry_only"

    def test_missing_env_falls_back_to_defaults(self, monkeypatch):
        for name in (
            "QUORUM_MIN_LIVE_RESPONSES",
            "QUORUM_REQUIRE_CORE_PROVIDER",
            "QUORUM_GRACE_WINDOW_SECONDS",
            "QUORUM_DISAGREEMENT_THRESHOLD",
            "QUORUM_LATE_ARRIVING_BEHAVIOR",
        ):
            monkeypatch.delenv(name, raising=False)

        policy = build_quorum_policy_from_env()
        assert policy == QuorumPolicy()

    def test_invalid_minimum_live_responses_rejected(self):
        with pytest.raises(ValueError):
            QuorumPolicy(minimum_live_responses=0)

    def test_negative_grace_window_rejected(self):
        with pytest.raises(ValueError):
            QuorumPolicy(grace_window_seconds=-1)

    def test_disagreement_threshold_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            QuorumPolicy(disagreement_threshold=1.5)
        with pytest.raises(ValueError):
            QuorumPolicy(disagreement_threshold=-0.1)

    def test_unsupported_late_arriving_behavior_rejected(self):
        with pytest.raises(ValueError):
            QuorumPolicy(late_arriving_behavior="do_something_undefined")

    def test_every_documented_late_arriving_behavior_is_accepted(self):
        for value in LATE_ARRIVING_BEHAVIORS:
            QuorumPolicy(late_arriving_behavior=value)  # must not raise

    def test_env_override_with_invalid_value_still_raises(self, monkeypatch):
        # Configuration errors must fail loudly, not silently fall back.
        monkeypatch.setenv("QUORUM_DISAGREEMENT_THRESHOLD", "5.0")
        with pytest.raises(ValueError):
            build_quorum_policy_from_env()


class TestProviderPolicyValidation:
    def test_empty_provider_id_rejected(self):
        with pytest.raises(ValueError):
            ProviderPolicy(provider_id="")

    def test_negative_priority_rejected(self):
        with pytest.raises(ValueError):
            ProviderPolicy(provider_id="model-x", priority=-1)

    def test_negative_grace_window_override_rejected(self):
        with pytest.raises(ValueError):
            ProviderPolicy(provider_id="model-x", grace_window_override_seconds=-2.0)

    def test_valid_policy_constructs_cleanly(self):
        policy = ProviderPolicy(
            provider_id="model-x",
            core_provider=True,
            priority=7,
            grace_window_override_seconds=2.5,
            timeout_policy_ref="MODEL_X_PROVIDER_TIMEOUT_SECONDS",
        )
        assert policy.core_provider is True
        assert policy.priority == 7


# --------------------------------------------------------------------------
# 8-11) Current pipeline behaviour is provably unchanged.
# --------------------------------------------------------------------------

class _SuccessfulProvider(Provider):
    id = "success"

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        return ProviderResult(text="real answer", model_used="test-live")


class _FailingProvider(Provider):
    id = "failure"

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        raise RuntimeError("provider unavailable")


class _QuickLiveProvider(Provider):
    def __init__(self, provider_id: str, provider_name: str, text: str):
        self.id = provider_id
        self.provider_name = provider_name
        self._text = text
        super().__init__(execution_timeout_seconds=5.0)

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        return ProviderResult(text=self._text, model_used="test-live")


class TestCurrentPipelineUnaffectedByPending:
    def test_successful_timed_generate_never_produces_pending(self):
        result = asyncio.run(_SuccessfulProvider().timed_generate("q", "s"))
        assert result.provider_status == PROVIDER_STATUS_LIVE
        assert result.provider_status in FINALIZED_PROVIDER_STATUSES
        assert result.provider_status != PROVIDER_STATUS_PENDING

    def test_failing_timed_generate_never_produces_pending(self):
        result = asyncio.run(_FailingProvider().timed_generate("q", "s"))
        assert result.provider_status == PROVIDER_STATUS_FAILED
        assert result.provider_status in FINALIZED_PROVIDER_STATUSES
        assert result.provider_status != PROVIDER_STATUS_PENDING

    def test_three_of_three_fast_providers_pipeline_unchanged(self):
        providers = [
            _QuickLiveProvider("model-a", "OpenAI", "OpenAI answer"),
            _QuickLiveProvider("model-c", "Gemini", "Gemini answer"),
            _QuickLiveProvider("model-e", "Mistral AI", "Mistral answer"),
        ]

        async def run_panel():
            return await asyncio.gather(
                *(provider.timed_generate("q", "s") for provider in providers)
            )

        started = time.perf_counter()
        results = asyncio.run(run_panel())
        elapsed = time.perf_counter() - started

        assert elapsed < 1.0
        assert [r.provider_status for r in results] == ["LIVE", "LIVE", "LIVE"]
        assert all(r.provider_status != PROVIDER_STATUS_PENDING for r in results)

    def test_pipeline_with_one_failed_provider_unchanged(self):
        providers = [
            _QuickLiveProvider("model-a", "OpenAI", "OpenAI answer"),
            _FailingProvider(),
            _QuickLiveProvider("model-e", "Mistral AI", "Mistral answer"),
        ]

        async def run_panel():
            return await asyncio.gather(
                *(provider.timed_generate("q", "s") for provider in providers)
            )

        results = asyncio.run(run_panel())

        assert [r.provider_status for r in results] == ["LIVE", "FAILED", "LIVE"]
        assert all(r.provider_status != PROVIDER_STATUS_PENDING for r in results)


class TestSynthesizerNeverReceivesPending:
    def test_eligible_synthesis_answers_excludes_pending(self):
        responses = [
            {"id": "model-a", "provider_status": "LIVE", "text": "answer A", "provider_key": "openai"},
            {"id": "model-c", "provider_status": "PENDING", "text": "", "provider_key": "gemini"},
            {"id": "model-e", "provider_status": "FAILED", "text": "", "provider_key": "mistral"},
        ]
        answers = eligible_synthesis_answers(responses, "LIVE")
        ids = {a["id"] for a in answers}
        assert ids == {"model-a"}
        assert "model-c" not in ids

    def test_eligible_synthesis_answers_ignores_pending_even_with_text(self):
        # A hypothetical PENDING placeholder that (incorrectly) carried text
        # must still never be treated as usable evidence.
        responses = [
            {"id": "model-c", "provider_status": "PENDING", "text": "partial content", "provider_key": "gemini"},
        ]
        assert eligible_synthesis_answers(responses, "LIVE") == []

    def test_validate_claim_analysis_rejects_pending_evidence(self):
        raw = {"execution_mode": "LIVE", "claims": []}
        answers = [{
            "provider_status": "PENDING",
            "provider_key": "gemini",
            "provider_response_id": "model-c",
            "text": "partial content",
        }]
        with pytest.raises(ValueError):
            validate_claim_analysis(raw, answers, citations=[], execution_mode="LIVE")


class TestFoundationNotWiredIntoRuntime:
    def test_server_module_does_not_import_policy_yet(self):
        # server.py's ModelResponse docstring/comment deliberately *mentions*
        # `providers.policy` in prose (pointing a future reader at it) — this
        # checks for an actual import statement, not that bare substring.
        server_source = (BACKEND_DIR / "server.py").read_text(encoding="utf-8")
        import_lines = [
            line.strip()
            for line in server_source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        assert not any("policy" in line for line in import_lines)

    def test_server_module_does_not_reference_pending_status_in_logic(self):
        # Every mention of PENDING in server.py must live in the
        # documentation comment on ModelResponse.provider_status — none may
        # appear in actual code (e.g. `== "PENDING"` or similar logic).
        server_source = (BACKEND_DIR / "server.py").read_text(encoding="utf-8")
        pending_lines = [
            line for line in server_source.splitlines() if "PENDING" in line
        ]
        assert pending_lines, "expected the documentation comment to still be present"
        assert all(line.strip().startswith("#") for line in pending_lines)
