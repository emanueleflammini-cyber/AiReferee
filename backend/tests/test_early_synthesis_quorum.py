"""Early Synthesis — Patch 2: quorum + grace window + late-arriving
background providers. Offline tests, no real API calls.

Two layers of tests:

1. Primitive-level, against `providers.early_synthesis.run_providers_with_quorum`
   directly — no FastAPI, no Mongo. Covers the core asyncio orchestration:
   quorum detection, core-provider requirement, the conservative
   disagreement gate, grace-window timing, no-cancellation, background-task
   anti-GC/consumption, and logging.
2. Integration-level, calling `server.compare_query` directly (bypassing
   FastAPI routing, so the test controls its own asyncio.run event loop end
   to end) against a tiny in-memory FakeDB — covers the "Scenario di test
   principale" (2 fast + 1 slow), proving the HTTP response does not wait
   for the slow provider, the synthesizer receives exactly the finalized
   providers, exactly one synthesis happens, and the late provider's real
   result is persisted afterwards without touching the already-returned
   Super Answer.

All simulated delays are tiny (hundredths of a second) — nothing here ever
sleeps for real seconds, let alone the real 4s/25s/60s production values.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "test_database_offline")

from providers.base import Provider, ProviderResult  # noqa: E402
from providers.policy import ProviderPolicy, QuorumPolicy, get_provider_policy  # noqa: E402
from providers.early_synthesis import (  # noqa: E402
    _BACKGROUND_TASKS,
    run_providers_with_quorum,
)

import server  # noqa: E402

# langdetect (used by providers.language.detect_language, called
# unconditionally by compare_query after synthesis — pre-existing code,
# unrelated to Early Synthesis) lazily loads its language-profile data on
# the first call in a process: a one-time ~0.1-0.4s cost. Warmed up once
# here, at module import time, so the timing assertions in the integration
# tests below (elapsed < SLOW, etc.) measure only early-synthesis
# behaviour, not this unrelated library's cold start.
from providers.language import detect_language as _warm_up_detect_language  # noqa: E402
_warm_up_detect_language(
    "Warm-up sentence so langdetect preloads its language profiles before any timed test runs."
)


# --------------------------------------------------------------------------
# Shared fixtures: a configurable fake provider and a tiny FakeDB.
# --------------------------------------------------------------------------

class _TimedProvider(Provider):
    """Succeeds (or fails) after a fixed, tiny, simulated delay."""

    def __init__(self, provider_id: str, delay: float, outcome: str = "live", text: str = "answer"):
        self.id = provider_id
        self.provider_name = provider_id
        self._delay = delay
        self._outcome = outcome  # "live" | "failed"
        self._text = text
        super().__init__(execution_timeout_seconds=5.0)

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        await asyncio.sleep(self._delay)
        if self._outcome == "failed":
            raise RuntimeError("simulated provider failure")
        return ProviderResult(text=self._text, model_used="test-model")


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def tokens_of(text: str) -> set:
    return set((text or "").lower().split())


def _similarity_fn(a: str, b: str) -> float:
    return jaccard(tokens_of(a), tokens_of(b))


class FakeCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    async def to_list(self, length=None):
        return self._items if length is None else self._items[:length]


class FakeCollection:
    """`update_one` simulates real matched_count semantics (keyed by "id"):
    a document must already exist (created by a prior upsert=True call) for
    a later upsert=False call to report matched_count=1 — this is what lets
    the race-condition tests below actually distinguish "the late write
    landed before/after the main write" instead of always seeing 0."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.inserted = []
        self.updated = []
        self.documents: dict[str, dict] = {}

    def find(self, _query=None, _projection=None):
        return FakeCursor(self.items)

    async def find_one(self, _query=None, _projection=None):
        return self.items[0] if self.items else None

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return SimpleNamespace(inserted_id="fake-id")

    async def update_one(self, query, update, upsert=False):
        self.updated.append((query, update, upsert))
        doc_id = query.get("id")
        set_fields = dict(update.get("$set", {}))
        existing = self.documents.get(doc_id)
        if existing is not None:
            existing.update(set_fields)
            return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            new_doc = dict(update.get("$setOnInsert", {}))
            new_doc.update(set_fields)
            new_doc.setdefault("id", doc_id)
            self.documents[doc_id] = new_doc
            return SimpleNamespace(matched_count=0, upserted_id=doc_id)
        return SimpleNamespace(matched_count=0, upserted_id=None)


class FakeDB:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        return self[name]


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(server, "db", db)
    return db


def _anonymous_identity():
    from auth import IdentityContext
    from providers.plans import Plan, entitlements_for
    return IdentityContext(
        user_id=None, plan=Plan.FREE, entitlements=entitlements_for(Plan.FREE), is_anonymous=True,
    )


# ==========================================================================
# 1) Primitive-level tests: run_providers_with_quorum
# ==========================================================================

FAST = 0.02
SLOW = 0.15
GRACE = 0.05


def _default_policy(**overrides) -> QuorumPolicy:
    base = dict(
        minimum_live_responses=2, require_core_provider=True,
        grace_window_seconds=GRACE, disagreement_threshold=0.0,
        late_arriving_behavior="cache_and_notify",
    )
    base.update(overrides)
    return QuorumPolicy(**base)


class TestScenarioAThreeFastProviders:
    def test_all_three_finalize_no_late_tasks(self):
        providers = [
            _TimedProvider("model-a", FAST, text="openai answer"),
            _TimedProvider("model-c", FAST, text="gemini answer"),
            _TimedProvider("model-e", FAST, text="mistral answer"),
        ]
        result = asyncio.run(
            run_providers_with_quorum(providers, "q", "s", _default_policy())
        )
        assert result.late_tasks == {}
        assert result.early_synthesis is False
        assert set(result.finalized.keys()) == {"model-a", "model-c", "model-e"}
        assert all(r.provider_status == "LIVE" for r in result.finalized.values())


class TestScenarioBTwoFastOneSlow:
    def test_quorum_reached_grace_expires_slow_provider_becomes_late(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.5, text="mistral answer"),
                _TimedProvider("model-c", SLOW, text="gemini answer"),
            ]
            started = time.perf_counter()
            result = await run_providers_with_quorum(
                providers, "q", "s", _default_policy(), similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            assert result.early_synthesis is True
            assert set(result.late_tasks.keys()) == {"model-c"}
            assert set(result.finalized.keys()) == {"model-a", "model-e"}
            assert result.quorum_reached_at_ms is not None
            # Cut off well before the slow provider's own delay, proving the
            # response path does not wait for it.
            assert elapsed < SLOW

            # Drain the still-pending late task before the event loop
            # closes, so nothing is abandoned mid-flight.
            await asyncio.sleep(SLOW + 0.1)

        asyncio.run(scenario())

    def test_late_provider_completes_in_background_after_cutoff(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.5, text="mistral answer"),
                _TimedProvider("model-c", SLOW, text="gemini answer"),
            ]
            completed: dict[str, ProviderResult] = {}

            async def on_late_complete(provider_id, result):
                completed[provider_id] = result

            result = await run_providers_with_quorum(
                providers, "q", "s", _default_policy(),
                similarity_fn=_similarity_fn, on_late_complete=on_late_complete,
            )
            late_task = result.late_tasks["model-c"]
            assert not late_task.done()  # still running right after cutoff
            assert "model-c" not in completed  # not yet — proves cutoff really preceded completion

            # Give the late task (and its persistence follow-up) time to
            # finish, in the SAME event loop — proving it genuinely
            # continues running after the early return.
            await asyncio.sleep(SLOW + 0.1)

            assert late_task.done()
            assert "model-c" in completed
            assert completed["model-c"].provider_status == "LIVE"
            assert completed["model-c"].text == "gemini answer"
            # Anti-GC reference dropped once done.
            assert late_task not in _BACKGROUND_TASKS

        asyncio.run(scenario())


class TestScenarioCQuorumWithoutCoreProvider:
    def test_two_non_core_live_does_not_trigger_early_cutoff(self):
        # Synthetic ids/policy so this test does not depend on which of the
        # 3 real production providers happens to be core.
        policies = {
            "prov-x": ProviderPolicy(provider_id="prov-x", core_provider=False),
            "prov-y": ProviderPolicy(provider_id="prov-y", core_provider=False),
            "prov-z": ProviderPolicy(provider_id="prov-z", core_provider=True),
        }

        def lookup(provider_id: str) -> ProviderPolicy:
            return policies[provider_id]

        providers = [
            _TimedProvider("prov-x", FAST, text="x answer"),
            _TimedProvider("prov-y", FAST * 1.2, text="y answer"),
            _TimedProvider("prov-z", SLOW, text="z answer"),  # the only core provider
        ]
        started = time.perf_counter()
        result = asyncio.run(
            run_providers_with_quorum(
                providers, "q", "s", _default_policy(), provider_policy_lookup=lookup,
            )
        )
        elapsed = time.perf_counter() - started

        # Quorum (2 LIVE) was numerically reachable at ~FAST*1.2, but
        # require_core_provider=True must have blocked early cutoff until
        # the core provider (prov-z, SLOW) also resolved — proven by the
        # elapsed time being close to SLOW, not to FAST*1.2 + grace.
        assert elapsed >= SLOW * 0.8
        assert result.early_synthesis is False
        assert result.late_tasks == {}
        assert set(result.finalized.keys()) == {"prov-x", "prov-y", "prov-z"}

    def test_require_core_provider_false_allows_two_non_core(self):
        policies = {
            "prov-x": ProviderPolicy(provider_id="prov-x", core_provider=False),
            "prov-y": ProviderPolicy(provider_id="prov-y", core_provider=False),
            "prov-z": ProviderPolicy(provider_id="prov-z", core_provider=True),
        }

        def lookup(provider_id: str) -> ProviderPolicy:
            return policies[provider_id]

        async def scenario():
            providers = [
                _TimedProvider("prov-x", FAST, text="x answer"),
                _TimedProvider("prov-y", FAST * 1.2, text="y answer"),
                _TimedProvider("prov-z", SLOW, text="z answer"),
            ]
            started = time.perf_counter()
            result = await run_providers_with_quorum(
                providers, "q", "s",
                _default_policy(require_core_provider=False),
                provider_policy_lookup=lookup,
            )
            elapsed = time.perf_counter() - started

            assert elapsed < SLOW
            assert result.early_synthesis is True
            assert set(result.late_tasks.keys()) == {"prov-z"}

            # Drain the still-pending late task before the loop closes.
            await asyncio.sleep(SLOW + 0.1)

        asyncio.run(scenario())


class TestScenarioDQuorumNeverReached:
    def test_only_one_live_response_ever_waits_for_full_finalization(self):
        providers = [
            _TimedProvider("model-a", FAST, text="openai answer"),
            _TimedProvider("model-c", FAST * 1.5, outcome="failed"),
            _TimedProvider("model-e", FAST * 2, outcome="failed"),
        ]
        result = asyncio.run(
            run_providers_with_quorum(providers, "q", "s", _default_policy())
        )
        assert result.early_synthesis is False
        assert result.late_tasks == {}
        assert result.quorum_reached_at_ms is None
        assert set(result.finalized.keys()) == {"model-a", "model-c", "model-e"}
        assert result.finalized["model-a"].provider_status == "LIVE"
        assert result.finalized["model-c"].provider_status == "FAILED"
        assert result.finalized["model-e"].provider_status == "FAILED"


class TestScenarioEFastFailure:
    def test_already_finalized_provider_causes_no_unnecessary_wait(self):
        providers = [
            _TimedProvider("model-c", FAST * 0.3, outcome="failed"),  # fails first, fastest
            _TimedProvider("model-a", FAST, text="openai answer"),
            _TimedProvider("model-e", FAST * 1.3, text="mistral answer"),
        ]
        started = time.perf_counter()
        result = asyncio.run(
            run_providers_with_quorum(providers, "q", "s", _default_policy())
        )
        elapsed = time.perf_counter() - started

        # Quorum (model-a + model-e, both LIVE, model-a core) is reached
        # right as the last of the two finishes — at that point model-c is
        # ALREADY finalized (it failed first), so there is nothing left
        # pending and the grace window must never be applied.
        assert result.early_synthesis is False
        assert result.late_tasks == {}
        assert elapsed < GRACE  # would be >= GRACE if an unnecessary wait were applied


class TestScenarioFLateProviderFails:
    def test_late_failure_is_consumed_and_reported_failed(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.5, text="mistral answer"),
                _TimedProvider("model-c", SLOW, outcome="failed"),
            ]
            completed: dict[str, ProviderResult] = {}

            async def on_late_complete(provider_id, result):
                completed[provider_id] = result

            result = await run_providers_with_quorum(
                providers, "q", "s", _default_policy(),
                similarity_fn=_similarity_fn, on_late_complete=on_late_complete,
            )
            assert result.early_synthesis is True
            # finalized (the already-returned "Super Answer" basis) is
            # untouched by what happens to the late provider afterwards.
            finalized_snapshot = dict(result.finalized)

            await asyncio.sleep(SLOW + 0.1)

            assert completed["model-c"].provider_status == "FAILED"
            assert completed["model-c"].text == ""
            # No crash, no leaked task, and the already-decided finalized
            # set is unchanged.
            assert result.finalized == finalized_snapshot

        asyncio.run(scenario())


class TestScenarioGNoMockInLiveQuorum:
    def test_mock_results_never_satisfy_quorum(self):
        class _MockProvider(Provider):
            def __init__(self, provider_id, delay):
                self.id = provider_id
                self.provider_name = provider_id
                self._delay = delay
                super().__init__(execution_timeout_seconds=5.0)

            async def generate(self, prompt, system):
                await asyncio.sleep(self._delay)
                return ProviderResult(text="mock answer", model_used="mock-model", is_mock=True)

        providers = [
            _MockProvider("model-a", FAST),
            _MockProvider("model-e", FAST * 1.2),
            _TimedProvider("model-c", SLOW, text="gemini answer"),
        ]
        started = time.perf_counter()
        result = asyncio.run(
            run_providers_with_quorum(providers, "q", "s", _default_policy())
        )
        elapsed = time.perf_counter() - started

        # Two MOCK results can never satisfy a LIVE-only quorum — the loop
        # must wait for model-c too, proven by elapsed being close to SLOW.
        assert elapsed >= SLOW * 0.8
        assert result.early_synthesis is False
        assert result.late_tasks == {}


class TestScenarioIGraceWindowConfigurable:
    @pytest.mark.parametrize("grace", [0.02, 0.08])
    def test_cutoff_scales_with_configured_grace_window(self, grace):
        async def scenario():
            slow_delay = grace + 0.3
            providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.2, text="mistral answer"),
                _TimedProvider("model-c", slow_delay, text="gemini answer"),
            ]
            started = time.perf_counter()
            result = await run_providers_with_quorum(
                providers, "q", "s", _default_policy(grace_window_seconds=grace),
            )
            elapsed = time.perf_counter() - started

            assert result.early_synthesis is True
            # Cutoff happens at roughly quorum_time + grace, not quorum_time
            # alone and not the slow provider's full delay.
            assert elapsed >= grace * 0.5
            assert elapsed < slow_delay

            # Drain the still-pending late task before the loop closes.
            await asyncio.sleep(slow_delay)

        asyncio.run(scenario())


class TestScenarioJProviderPolicyConfigurable:
    def test_ineligible_for_quorum_provider_never_counts(self):
        policies = {
            "model-a": ProviderPolicy(provider_id="model-a", core_provider=True, eligible_for_quorum=False),
            "model-e": ProviderPolicy(provider_id="model-e", core_provider=False),
        }

        def lookup(provider_id: str) -> ProviderPolicy:
            return policies.get(provider_id, get_provider_policy(provider_id))

        providers = [
            _TimedProvider("model-a", FAST, text="openai answer"),
            _TimedProvider("model-e", FAST * 1.2, text="mistral answer"),
        ]
        # Only model-e is quorum-eligible -> with minimum_live_responses=2
        # quorum can never be reached from these two alone.
        result = asyncio.run(
            run_providers_with_quorum(
                providers, "q", "s", _default_policy(), provider_policy_lookup=lookup,
            )
        )
        assert result.early_synthesis is False
        assert result.late_tasks == {}


class TestScenarioKBackgroundTaskHygiene:
    def test_task_referenced_then_cleaned_up(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.2, text="mistral answer"),
                _TimedProvider("model-c", SLOW, text="gemini answer"),
            ]
            before = set(_BACKGROUND_TASKS)
            result = await run_providers_with_quorum(
                providers, "q", "s", _default_policy(),
            )
            late_task = result.late_tasks["model-c"]
            assert late_task in _BACKGROUND_TASKS
            assert late_task not in before

            await asyncio.sleep(SLOW + 0.1)
            assert late_task not in _BACKGROUND_TASKS

        asyncio.run(scenario())

    def test_never_cancels_the_late_task(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.2, text="mistral answer"),
                _TimedProvider("model-c", SLOW, text="gemini answer"),
            ]
            result = await run_providers_with_quorum(
                providers, "q", "s", _default_policy(),
            )
            late_task = result.late_tasks["model-c"]
            assert not late_task.cancelled()
            await asyncio.sleep(SLOW + 0.1)
            assert not late_task.cancelled()
            assert late_task.exception() is None

        asyncio.run(scenario())


class TestDisagreementGate:
    def test_dissimilar_pair_blocks_early_cutoff_until_third_arrives(self):
        providers = [
            _TimedProvider("model-a", FAST, text="cats are wonderful pets"),
            _TimedProvider("model-e", FAST * 1.2, text="quantum entanglement explained simply"),
            _TimedProvider("model-c", SLOW, text="cats are wonderful pets too"),
        ]
        started = time.perf_counter()
        result = asyncio.run(
            run_providers_with_quorum(
                providers, "q", "s",
                _default_policy(disagreement_threshold=0.5),
                similarity_fn=_similarity_fn,
            )
        )
        elapsed = time.perf_counter() - started

        # Wildly dissimilar first two -> gate must block the early cutoff,
        # so the loop waits for the third provider too.
        assert elapsed >= SLOW * 0.8
        assert result.early_synthesis is False

    def test_similar_pair_allows_early_cutoff(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="cats are wonderful pets"),
                _TimedProvider("model-e", FAST * 1.2, text="cats are wonderful animals"),
                _TimedProvider("model-c", SLOW, text="cats are wonderful pets too"),
            ]
            started = time.perf_counter()
            result = await run_providers_with_quorum(
                providers, "q", "s",
                _default_policy(disagreement_threshold=0.3),
                similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            assert elapsed < SLOW
            assert result.early_synthesis is True

            await asyncio.sleep(SLOW + 0.1)

        asyncio.run(scenario())

    def test_disabled_gate_via_zero_threshold_always_allows_cutoff(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="cats are wonderful pets"),
                _TimedProvider("model-e", FAST * 1.2, text="quantum entanglement explained"),
                _TimedProvider("model-c", SLOW, text="irrelevant"),
            ]
            result = await run_providers_with_quorum(
                providers, "q", "s",
                _default_policy(disagreement_threshold=0.0),
                similarity_fn=_similarity_fn,
            )
            assert result.early_synthesis is True

            await asyncio.sleep(SLOW + 0.1)

        asyncio.run(scenario())


class TestLogging:
    def test_key_lifecycle_events_are_logged_without_content(self, caplog):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="super secret answer A"),
                _TimedProvider("model-e", FAST * 1.2, text="super secret answer E"),
                _TimedProvider("model-c", SLOW, text="super secret answer C"),
            ]
            with caplog.at_level(logging.INFO):
                result = await run_providers_with_quorum(
                    providers, "super secret prompt", "super secret system",
                    _default_policy(),
                )
                await asyncio.sleep(SLOW + 0.1)
            return result

        asyncio.run(scenario())

        text = caplog.text
        assert "early_synthesis_provider_finalized" in text
        assert "early_synthesis_quorum_reached" in text
        assert "early_synthesis_grace_window_started" in text
        assert "early_synthesis_grace_window_ended" in text
        assert "early_synthesis_late_provider_completed" in text
        assert "super secret" not in text


# ==========================================================================
# 2) Integration-level: server.compare_query end to end (FakeDB, no HTTP).
# ==========================================================================

def _synth_payload(**overrides) -> dict:
    payload = dict(
        text="Synthesized answer.",
        structured_conclusion=None,
        schema_version="2.1",
        model_used="test-synth-model",
        latency_ms=5,
        cost_usd=0.001,
        claims=[],
        citations=[],
        claim_schema_version=None,
        claim_analysis_status="SUCCESS",
        claim_analysis_error=None,
        repair_attempted=False,
    )
    payload.update(overrides)
    return payload


class TestCompareQueryEarlySynthesisIntegration:
    def _seed_query(self, fake_db, query_id="q1"):
        fake_db["queries"].items = [{
            "id": query_id,
            "prompt": "What is the latest news today about this topic?",
            "strategy": "balanced",
            "audience": "professional",
            "format": "paragraph",
            "answer_language": "en",
        }]

    def test_response_does_not_wait_for_slow_provider_and_synthesis_runs_once(self, fake_db, monkeypatch):
        self._seed_query(fake_db)
        monkeypatch.setattr(
            server, "DEFAULT_QUORUM_POLICY",
            QuorumPolicy(
                minimum_live_responses=2, require_core_provider=True,
                grace_window_seconds=GRACE, disagreement_threshold=0.0,
                late_arriving_behavior="cache_and_notify",
            ),
        )
        openai_p = _TimedProvider("model-a", FAST, text="OpenAI answer")
        mistral_p = _TimedProvider("model-e", FAST * 1.3, text="Mistral answer")
        gemini_p = _TimedProvider("model-c", SLOW, text="Gemini answer")

        mocked_synth_instance = SimpleNamespace(
            available=True, synthesize=AsyncMock(return_value=_synth_payload()),
        )

        async def scenario():
            with patch.object(server, "providers_for_execution", return_value=("LIVE", [openai_p, mistral_p, gemini_p])), \
                 patch.object(server, "Synthesizer", return_value=mocked_synth_instance) as mocked_synth_cls:
                started = time.perf_counter()
                response = await server.compare_query("q1", _anonymous_identity())
                elapsed = time.perf_counter() - started

                # The HTTP response must not have waited for Gemini (SLOW).
                assert elapsed < SLOW

                # Exactly the two finalized providers appear — no PENDING
                # placeholder for Gemini, no premature synthesis-triggered
                # data for it either.
                response_ids = {r.id for r in response.responses}
                assert response_ids == {"model-a", "model-e"}
                assert response.trusted_conclusion == "Synthesized answer."

                # Synthesizer was invoked exactly once, with exactly the two
                # finalized providers — never Gemini, never PENDING.
                assert mocked_synth_cls.call_count == 1
                mocked_synth_instance.synthesize.assert_awaited_once()
                synth_call_answers = mocked_synth_instance.synthesize.await_args.args[1]
                synth_provider_ids = {a["id"] for a in synth_call_answers}
                assert synth_provider_ids == {"model-a", "model-e"}

                # compare_logs has exactly the two finalized rows so far —
                # nothing for Gemini yet.
                logged_ids_so_far = {row["provider_id"] for row in fake_db["compare_logs"].inserted}
                assert logged_ids_so_far == {"model-a", "model-e"}

                # Let the late Gemini task (and its persistence follow-up)
                # complete, in the same event loop.
                await asyncio.sleep(SLOW + 0.15)

                # Real, late outcome persisted — but the already-returned
                # response object is untouched.
                assert response.trusted_conclusion == "Synthesized answer."
                assert {r.id for r in response.responses} == {"model-a", "model-e"}

                # No second synthesis was ever triggered by the late arrival.
                assert mocked_synth_cls.call_count == 1
                mocked_synth_instance.synthesize.assert_awaited_once()

                # The late provider's real result is now persisted.
                late_logs = [
                    row for row in fake_db["compare_logs"].inserted
                    if row["provider_id"] == "model-c"
                ]
                assert len(late_logs) == 1
                assert late_logs[0]["provider_status"] == "LIVE"
                assert late_logs[0]["is_late_arriving"] is True

                late_conclusion_updates = [
                    (query, update, upsert) for query, update, upsert in fake_db["conclusions"].updated
                    if "late_provider_results.model-c" in update.get("$set", {})
                ]
                assert len(late_conclusion_updates) == 1
                late_payload = late_conclusion_updates[0][1]["$set"]["late_provider_results.model-c"]
                assert late_payload["provider_status"] == "LIVE"
                assert late_payload["text"] == "Gemini answer"

                # The main synchronous write is untouched by the late one —
                # disjoint fields, no overwrite. There must be at least one
                # earlier update_one call carrying the real "responses"/
                # "trusted_conclusion" fields (the synchronous write).
                main_updates = [
                    (query, update, upsert) for query, update, upsert in fake_db["conclusions"].updated
                    if "trusted_conclusion" in update.get("$set", {})
                ]
                assert len(main_updates) == 1
                assert main_updates[0][1]["$set"]["trusted_conclusion"] == "Synthesized answer."

        asyncio.run(scenario())

    def test_three_fast_providers_end_to_end_matches_previous_shape(self, fake_db, monkeypatch):
        self._seed_query(fake_db, query_id="q2")
        monkeypatch.setattr(
            server, "DEFAULT_QUORUM_POLICY",
            QuorumPolicy(
                minimum_live_responses=2, require_core_provider=True,
                grace_window_seconds=GRACE, disagreement_threshold=0.0,
                late_arriving_behavior="cache_and_notify",
            ),
        )
        providers = [
            _TimedProvider("model-a", FAST, text="OpenAI answer"),
            _TimedProvider("model-c", FAST * 1.1, text="Gemini answer"),
            _TimedProvider("model-e", FAST * 1.2, text="Mistral answer"),
        ]
        mocked_synth_instance = SimpleNamespace(
            available=True, synthesize=AsyncMock(return_value=_synth_payload()),
        )

        async def scenario():
            with patch.object(server, "providers_for_execution", return_value=("LIVE", providers)), \
                 patch.object(server, "Synthesizer", return_value=mocked_synth_instance) as mocked_synth_cls:
                response = await server.compare_query("q2", _anonymous_identity())

                # All three appear — nothing held back, matching the
                # pre-Patch-2 asyncio.gather shape exactly.
                assert {r.id for r in response.responses} == {"model-a", "model-c", "model-e"}
                assert all(r.provider_status == "LIVE" for r in response.responses)
                mocked_synth_cls.call_count == 1
                synth_call_answers = mocked_synth_instance.synthesize.await_args.args[1]
                assert {a["id"] for a in synth_call_answers} == {"model-a", "model-c", "model-e"}

        asyncio.run(scenario())


# ==========================================================================
# 3) Performance comparison — PRIMA (asyncio.gather) vs DOPO (quorum).
# ==========================================================================

class TestPerformanceSimulatedComparison:
    """Item 20: a simulated (no real seconds) demonstration that the old
    all-or-nothing wait made total latency == the slowest provider, while
    the new quorum+grace mechanism returns as soon as quorum+grace allow,
    with the slow provider's task provably still running afterwards."""

    def test_gather_waits_for_the_slow_provider_quorum_does_not(self):
        async def scenario():
            # PRIMA: the exact mechanism compare_query used before this
            # patch — asyncio.gather waits for every provider, so total
            # time == the slowest one, regardless of quorum/policy.
            before_providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.2, text="mistral answer"),
                _TimedProvider("model-c", SLOW, text="gemini answer"),
            ]
            started = time.perf_counter()
            await asyncio.gather(
                *(p.timed_generate("q", "s") for p in before_providers)
            )
            gather_elapsed = time.perf_counter() - started
            assert gather_elapsed >= SLOW * 0.9  # dominated by the slow provider

            # DOPO: same three providers, same delays, through
            # run_providers_with_quorum — the slow one becomes "late"
            # instead of blocking the return.
            after_providers = [
                _TimedProvider("model-a", FAST, text="openai answer"),
                _TimedProvider("model-e", FAST * 1.2, text="mistral answer"),
                _TimedProvider("model-c", SLOW, text="gemini answer"),
            ]
            completed_late: dict[str, ProviderResult] = {}

            async def on_late_complete(provider_id, result):
                completed_late[provider_id] = result

            started = time.perf_counter()
            result = await run_providers_with_quorum(
                after_providers, "q", "s", _default_policy(),
                on_late_complete=on_late_complete,
            )
            quorum_elapsed = time.perf_counter() - started

            # DOPO is meaningfully faster than PRIMA for the identical
            # slow-provider scenario — the core claim of this patch. (Not
            # asserting a tight ratio: with GRACE=0.05s and SLOW=0.15s the
            # two are close enough that scheduling jitter could flip a
            # stricter bound; the SLOW-relative assertions below are the
            # more robust proof.)
            assert quorum_elapsed < gather_elapsed * 0.75
            assert quorum_elapsed < SLOW
            assert result.early_synthesis is True
            assert "model-c" in result.late_tasks
            # At the moment "the response would be returned", the slow
            # provider's task has demonstrably not finished yet.
            assert not result.late_tasks["model-c"].done()
            assert "model-c" not in completed_late

            # ... and it continues running, and completes, strictly AFTER
            # the point where DOPO already "returned" — proving the
            # background continuation, not just a faster synchronous path.
            await asyncio.sleep(SLOW + 0.1)
            assert "model-c" in completed_late
            assert completed_late["model-c"].provider_status == "LIVE"

        asyncio.run(scenario())


# ==========================================================================
# 4) Late-provider persistence race condition fix.
#
# Bug: a late provider can finish WHILE compare_query is still inside the
# (potentially multi-second) Synthesizer call — i.e. strictly BEFORE
# compare_query's own main db.conclusions.update_one write, not only after
# the HTTP response. Its persistence used to attempt an upsert=False update
# immediately, hitting matched_count=0 (conclusion document did not exist
# yet) and silently losing the late result. Fixed with an asyncio.Event
# (`conclusion_saved`, created once per compare_query call) that the late
# persistence path awaits before writing — set in a `finally` right after
# the main write is attempted, so it always fires exactly once regardless
# of that write's outcome.
# ==========================================================================

class TestLateProviderRaceConditionFix:
    def _seed_query(self, fake_db, query_id):
        fake_db["queries"].items = [{
            "id": query_id,
            "prompt": "What is the latest news today about this topic?",
            "strategy": "balanced",
            "audience": "professional",
            "format": "paragraph",
            "answer_language": "en",
        }]

    def test_late_provider_finishes_during_synthesis_before_main_write(self, fake_db, monkeypatch):
        """The exact scenario from the report: C completes mid-synthesis,
        strictly before the main conclusions write — must still land in
        late_provider_results, Super Answer unchanged, no second synthesis,
        no exception/leak."""
        query_id = "race-during-synth"
        self._seed_query(fake_db, query_id)
        monkeypatch.setattr(
            server, "DEFAULT_QUORUM_POLICY",
            QuorumPolicy(
                minimum_live_responses=2, require_core_provider=True,
                grace_window_seconds=0.03, disagreement_threshold=0.0,
                late_arriving_behavior="cache_and_notify",
            ),
        )
        openai_p = _TimedProvider("model-a", 0.01, text="OpenAI answer")
        mistral_p = _TimedProvider("model-e", 0.015, text="Mistral answer")
        # Finishes at ~0.08s — well inside the synthesis window below
        # (which runs from ~quorum+grace ≈ 0.03s to ≈ 0.03+0.15 = 0.18s),
        # i.e. strictly before the main conclusions write.
        gemini_p = _TimedProvider("model-c", 0.08, text="Gemini answer")

        synth_delay = 0.15

        async def slow_synthesize(*_a, **_kw):
            await asyncio.sleep(synth_delay)
            return _synth_payload()

        mocked_synth_instance = SimpleNamespace(available=True, synthesize=slow_synthesize)

        async def scenario():
            with patch.object(server, "providers_for_execution", return_value=("LIVE", [openai_p, mistral_p, gemini_p])), \
                 patch.object(server, "Synthesizer", return_value=mocked_synth_instance) as mocked_synth_cls:
                response = await server.compare_query(query_id, _anonymous_identity())

                # Super Answer as expected, from exactly the two finalized
                # providers — model-c's mid-flight completion never leaked
                # into this response.
                assert response.trusted_conclusion == "Synthesized answer."
                assert {r.id for r in response.responses} == {"model-a", "model-e"}
                assert mocked_synth_cls.call_count == 1

                # By now model-c's task has long finished (0.08s) and was
                # parked waiting on `conclusion_saved` for most of the
                # synthesis window; the event was set right before
                # compare_query returned, which only *schedules* the
                # follow-up task's resumption — give the loop one tick to
                # actually run it to completion.
                await asyncio.sleep(0.02)

                assert mocked_synth_cls.call_count == 1  # still no second synthesis

                late_doc = fake_db["conclusions"].documents.get(query_id)
                assert late_doc is not None
                assert late_doc.get("trusted_conclusion") == "Synthesized answer."  # untouched
                assert "late_provider_results.model-c" in late_doc
                late_payload = late_doc["late_provider_results.model-c"]
                assert late_payload["provider_status"] == "LIVE"
                assert late_payload["text"] == "Gemini answer"

                # The late write succeeded (matched an existing document) —
                # not a lost update.
                late_update_calls = [
                    (q, u, up) for q, u, up in fake_db["conclusions"].updated
                    if "late_provider_results.model-c" in u.get("$set", {})
                ]
                assert len(late_update_calls) == 1

        asyncio.run(scenario())

    def test_late_provider_finishes_after_main_write_still_works(self, fake_db, monkeypatch):
        """Non-race path: the late provider resolves well after the main
        write — must still work exactly as before this fix."""
        query_id = "race-after-write"
        self._seed_query(fake_db, query_id)
        monkeypatch.setattr(
            server, "DEFAULT_QUORUM_POLICY",
            QuorumPolicy(
                minimum_live_responses=2, require_core_provider=True,
                grace_window_seconds=GRACE, disagreement_threshold=0.0,
                late_arriving_behavior="cache_and_notify",
            ),
        )
        openai_p = _TimedProvider("model-a", FAST, text="OpenAI answer")
        mistral_p = _TimedProvider("model-e", FAST * 1.3, text="Mistral answer")
        gemini_p = _TimedProvider("model-c", SLOW, text="Gemini answer")
        mocked_synth_instance = SimpleNamespace(
            available=True, synthesize=AsyncMock(return_value=_synth_payload()),
        )

        async def scenario():
            with patch.object(server, "providers_for_execution", return_value=("LIVE", [openai_p, mistral_p, gemini_p])), \
                 patch.object(server, "Synthesizer", return_value=mocked_synth_instance):
                await server.compare_query(query_id, _anonymous_identity())

                # Main write has already happened (synthesize is a fast
                # AsyncMock) — the document exists before model-c resolves.
                assert query_id in fake_db["conclusions"].documents

                await asyncio.sleep(SLOW + 0.15)

                late_doc = fake_db["conclusions"].documents[query_id]
                assert "late_provider_results.model-c" in late_doc
                assert late_doc["late_provider_results.model-c"]["provider_status"] == "LIVE"

        asyncio.run(scenario())

    def test_late_provider_failure_is_recorded_coherently(self, fake_db, monkeypatch):
        query_id = "race-late-fails"
        self._seed_query(fake_db, query_id)
        monkeypatch.setattr(
            server, "DEFAULT_QUORUM_POLICY",
            QuorumPolicy(
                minimum_live_responses=2, require_core_provider=True,
                grace_window_seconds=0.03, disagreement_threshold=0.0,
                late_arriving_behavior="cache_and_notify",
            ),
        )
        openai_p = _TimedProvider("model-a", 0.01, text="OpenAI answer")
        mistral_p = _TimedProvider("model-e", 0.015, text="Mistral answer")
        gemini_p = _TimedProvider("model-c", 0.08, outcome="failed")
        mocked_synth_instance = SimpleNamespace(
            available=True, synthesize=AsyncMock(return_value=_synth_payload()),
        )

        async def scenario():
            with patch.object(server, "providers_for_execution", return_value=("LIVE", [openai_p, mistral_p, gemini_p])), \
                 patch.object(server, "Synthesizer", return_value=mocked_synth_instance):
                response = await server.compare_query(query_id, _anonymous_identity())
                await asyncio.sleep(0.15)

                late_doc = fake_db["conclusions"].documents.get(query_id)
                assert late_doc is not None
                late_payload = late_doc["late_provider_results.model-c"]
                assert late_payload["provider_status"] == "FAILED"
                assert late_payload["text"] == ""
                # Super Answer (already returned) unaffected by the late failure.
                assert response.trusted_conclusion == "Synthesized answer."

        asyncio.run(scenario())

    def test_matched_count_zero_is_logged_not_silently_treated_as_success(self, fake_db, caplog):
        """Direct unit-level proof of the requirement: if the conclusion
        document genuinely never existed (main write failed too — a real
        failure, not a race), the late write's matched_count=0 must be
        detected and logged, never silently swallowed."""
        async def scenario():
            event = asyncio.Event()
            event.set()  # no race to wait out — the doc simply never existed
            result = ProviderResult(text="Gemini answer", provider_status="LIVE", model_used="gemini-x")
            with caplog.at_level(logging.WARNING):
                await server._persist_late_provider_result(
                    "model-c", result,
                    query_id="query-with-no-conclusion-doc",
                    specs_by_id={},
                    execution_mode="LIVE",
                    conclusion_saved=event,
                )
            assert "early_synthesis_late_provider_result_not_attached" in caplog.text
            # The attempt itself still happened — a detected no-op, not a
            # skipped or silently-successful one.
            late_update_calls = [
                (q, u, up) for q, u, up in fake_db["conclusions"].updated
                if "late_provider_results.model-c" in u.get("$set", {})
            ]
            assert len(late_update_calls) == 1
            assert "query-with-no-conclusion-doc" not in fake_db["conclusions"].documents

        asyncio.run(scenario())

    def test_late_provider_never_waits_past_its_bounded_safety_timeout(self, fake_db, monkeypatch):
        """If the main write's own conclusion_saved.set() somehow never
        fires (pathological case — e.g. compare_query raised before
        reaching it), the late persistence must not hang forever."""
        monkeypatch.setattr(server, "_CONCLUSION_SAVED_WAIT_TIMEOUT_SECONDS", 0.03)

        async def scenario():
            never_set_event = asyncio.Event()  # deliberately never .set()
            result = ProviderResult(text="Gemini answer", provider_status="LIVE", model_used="gemini-x")
            started = time.perf_counter()
            await server._persist_late_provider_result(
                "model-c", result,
                query_id="query-that-never-saves",
                specs_by_id={},
                execution_mode="LIVE",
                conclusion_saved=never_set_event,
            )
            elapsed = time.perf_counter() - started
            # Bounded by the (monkeypatched, tiny) safety timeout, not stuck.
            assert elapsed < 0.5

        asyncio.run(scenario())
