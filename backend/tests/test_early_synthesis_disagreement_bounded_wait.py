"""Early Synthesis — bounded wait after a disagreement-gate failure
(fix/early-synthesis-disagreement-bounded-wait). Offline tests, no real API
calls, no real seconds beyond hundredths.

Reproduces the real production incident (query_id
0f07deb2-ed45-4acb-8afe-a3a1c3de8a2a): OpenAI LIVE, Mistral LIVE shortly
after (raw quorum satisfied: 2 LIVE, core provider present), disagreement
gate failed (similarity 0.1992 < 0.35 threshold), and the loop used to keep
waiting for Gemini's full ~50.9s (2x25s timeout + retry) before synthesis
could start at all. This patch adds a separate, bounded
disagreement_wait_seconds deadline: once it expires (or the pending
provider resolves first, one way or the other), the loop proceeds with the
LIVE responses already in hand -- the pending provider is never cancelled
and keeps running through the existing late-provider mechanism, unchanged.

Two layers, matching test_early_synthesis_quorum.py's structure:
1. Primitive-level, against run_providers_with_quorum directly.
2. Integration-level, against server.compare_query with a FakeDB, for the
   "late result actually gets persisted, Super Answer never regenerated"
   requirements that only make sense end to end.
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
from providers.policy import ProviderPolicy, QuorumPolicy  # noqa: E402
from providers.early_synthesis import (  # noqa: E402
    _BACKGROUND_TASKS,
    run_providers_with_quorum,
)

import server  # noqa: E402

from providers.language import detect_language as _warm_up_detect_language  # noqa: E402
_warm_up_detect_language(
    "Warm-up sentence so langdetect preloads its language profiles before any timed test runs."
)


# --------------------------------------------------------------------------
# Shared fixtures.
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


# Wildly dissimilar (Jaccard 0.0) -- mirrors the real production gate
# failure (similarity_score=0.1992 against threshold=0.35).
DISSIMILAR_A = "cats are wonderful pets"
DISSIMILAR_B = "quantum entanglement explained simply"
# Similar enough (Jaccard 0.6) to pass a 0.35 threshold.
SIMILAR_A = "cats are wonderful pets"
SIMILAR_B = "cats are wonderful animals"


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


OPENAI_DELAY = 0.02
MISTRAL_DELAY = 0.04
WAIT_SECONDS = 0.15
GEMINI_VERY_SLOW_DELAY = 0.8
GEMINI_WITHIN_WAIT_DELAY = 0.10
# Deliberately well-separated from MISTRAL_DELAY (not just a few ms later)
# so the two completions land in distinct asyncio.wait(FIRST_COMPLETED)
# batches even under test-runner scheduling jitter -- otherwise Mistral's
# LIVE result and Gemini's FAILED result could be observed together in the
# same batch, and the bounded wait would never actually start before the
# fast-path fires (a different, also-valid path, but not what this
# scenario is meant to exercise).
GEMINI_FAIL_DELAY = 0.12


def _policy(**overrides) -> QuorumPolicy:
    base = dict(
        minimum_live_responses=2,
        require_core_provider=True,
        grace_window_seconds=0.02,
        disagreement_threshold=0.35,
        disagreement_wait_seconds=WAIT_SECONDS,
    )
    base.update(overrides)
    return QuorumPolicy(**base)


# core providers for these tests: model-a (OpenAI) and model-c (Gemini),
# matching providers/policy.py DEFAULT_PROVIDER_POLICIES. model-e (Mistral)
# is non-core -- same real-world classification as production.
from providers.policy import get_provider_policy  # noqa: E402


# ==========================================================================
# 1) Primitive-level tests.
# ==========================================================================

class TestAProductionScenarioReproduction:
    def test_disagreement_wait_starts_and_expires_synthesis_proceeds_without_gemini(self):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_VERY_SLOW_DELAY, text="irrelevant")

            started = time.perf_counter()
            result = await run_providers_with_quorum(
                [openai_p, mistral_p, gemini_p], "q", "s",
                _policy(), similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            # Proceeded once the bounded disagreement wait expired -- long
            # before Gemini's own (very slow) delay.
            assert elapsed < GEMINI_VERY_SLOW_DELAY * 0.5
            assert elapsed >= MISTRAL_DELAY + WAIT_SECONDS * 0.5
            assert result.early_synthesis is True
            assert set(result.finalized.keys()) == {"model-a", "model-e"}
            assert set(result.late_tasks.keys()) == {"model-c"}
            assert result.disagreement_wait_actual_ms > 0

            # Gemini keeps running in the background, not cancelled.
            late_task = result.late_tasks["model-c"]
            assert not late_task.cancelled()
            await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)

        asyncio.run(scenario())

    def test_key_events_are_logged_without_response_content(self, caplog):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider(
                "model-c", GEMINI_VERY_SLOW_DELAY, text="super secret gemini answer"
            )
            with caplog.at_level(logging.INFO):
                result = await run_providers_with_quorum(
                    [openai_p, mistral_p, gemini_p], "super secret prompt", "s",
                    _policy(), similarity_fn=_similarity_fn, correlation_id="prod-repro",
                )
                await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)
            return result

        asyncio.run(scenario())
        text = caplog.text
        assert "early_synthesis_raw_quorum_reached" in text
        assert "early_synthesis_disagreement_wait_started" in text
        assert "wait_seconds=" in text
        assert "early_synthesis_disagreement_wait_completed" in text
        assert "reason=deadline_expired" in text
        assert "early_synthesis_disagreement_forced_proceed" in text
        assert "live_provider_ids=" in text
        assert "similarity_score=" in text
        assert "super secret" not in text


class TestBThirdProviderArrivesWithinWait:
    def test_all_three_used_when_gemini_arrives_before_deadline(self):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider(
                "model-c", GEMINI_WITHIN_WAIT_DELAY, text="cats are wonderful pets and more"
            )

            started = time.perf_counter()
            result = await run_providers_with_quorum(
                [openai_p, mistral_p, gemini_p], "q", "s",
                _policy(), similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            assert result.early_synthesis is False
            assert result.late_tasks == {}
            assert set(result.finalized.keys()) == {"model-a", "model-e", "model-c"}
            assert all(r.provider_status == "LIVE" for r in result.finalized.values())
            # Proceeded once Gemini (the pending provider) arrived -- not
            # held open for any remaining part of the wait window.
            assert elapsed < MISTRAL_DELAY + WAIT_SECONDS

        asyncio.run(scenario())

    def test_third_arrival_logs_wait_completed_reason(self, caplog):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider(
                "model-c", GEMINI_WITHIN_WAIT_DELAY, text="cats are wonderful pets and more"
            )
            with caplog.at_level(logging.INFO):
                await run_providers_with_quorum(
                    [openai_p, mistral_p, gemini_p], "q", "s",
                    _policy(), similarity_fn=_similarity_fn, correlation_id="third-arrives",
                )

        asyncio.run(scenario())
        assert "early_synthesis_disagreement_wait_completed" in caplog.text
        assert "reason=third_provider_arrived" in caplog.text
        assert "early_synthesis_disagreement_forced_proceed" not in caplog.text


class TestCPendingProviderFailsDuringWait:
    def test_proceeds_immediately_when_gemini_fails_before_deadline(self):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_FAIL_DELAY, outcome="failed")

            started = time.perf_counter()
            result = await run_providers_with_quorum(
                [openai_p, mistral_p, gemini_p], "q", "s",
                _policy(), similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            assert result.early_synthesis is False
            assert result.late_tasks == {}
            assert set(result.finalized.keys()) == {"model-a", "model-e", "model-c"}
            assert result.finalized["model-c"].provider_status == "FAILED"
            # Proceeded right when Gemini failed -- not held open for the
            # rest of the disagreement wait window.
            assert elapsed < MISTRAL_DELAY + WAIT_SECONDS * 0.9

        asyncio.run(scenario())

    def test_fast_path_logs_pending_provider_failed_reason(self, caplog):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_FAIL_DELAY, outcome="failed")
            with caplog.at_level(logging.INFO):
                await run_providers_with_quorum(
                    [openai_p, mistral_p, gemini_p], "q", "s",
                    _policy(), similarity_fn=_similarity_fn, correlation_id="pending-fails",
                )

        asyncio.run(scenario())
        assert "early_synthesis_disagreement_wait_completed" in caplog.text
        assert "reason=pending_provider_failed" in caplog.text
        assert "early_synthesis_disagreement_forced_proceed" in caplog.text


class TestDGateAlreadyPassing:
    def test_existing_quorum_grace_behavior_unaffected(self):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=SIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=SIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_VERY_SLOW_DELAY, text="irrelevant")

            started = time.perf_counter()
            result = await run_providers_with_quorum(
                [openai_p, mistral_p, gemini_p], "q", "s",
                _policy(), similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            assert result.early_synthesis is True
            assert set(result.late_tasks.keys()) == {"model-c"}
            # Cut off by the (small) grace window, not by the disagreement
            # wait -- proves the gate passing skips the new mechanism
            # entirely, exactly like before this patch.
            assert elapsed < MISTRAL_DELAY + WAIT_SECONDS
            assert result.disagreement_wait_actual_ms == 0

            await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)

        asyncio.run(scenario())

    def test_no_disagreement_wait_log_lines_when_gate_passes(self, caplog):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=SIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=SIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_VERY_SLOW_DELAY, text="irrelevant")
            with caplog.at_level(logging.INFO):
                await run_providers_with_quorum(
                    [openai_p, mistral_p, gemini_p], "q", "s",
                    _policy(), similarity_fn=_similarity_fn, correlation_id="gate-passes",
                )
                await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)

        asyncio.run(scenario())
        assert "early_synthesis_disagreement_wait_started" not in caplog.text
        assert "early_synthesis_disagreement_forced_proceed" not in caplog.text
        assert "early_synthesis_quorum_reached" in caplog.text


class TestETwoNonCoreLiveNoForcedProceed:
    def test_no_forced_proceed_without_core_provider(self):
        policies = {
            "prov-x": ProviderPolicy(provider_id="prov-x", core_provider=False),
            "prov-y": ProviderPolicy(provider_id="prov-y", core_provider=False),
            "prov-z": ProviderPolicy(provider_id="prov-z", core_provider=True),
        }

        def lookup(provider_id: str) -> ProviderPolicy:
            return policies[provider_id]

        providers = [
            _TimedProvider("prov-x", OPENAI_DELAY, text=DISSIMILAR_A),
            _TimedProvider("prov-y", MISTRAL_DELAY, text=DISSIMILAR_B),
            _TimedProvider("prov-z", GEMINI_FAIL_DELAY * 1.2, text="z answer"),
        ]
        started = time.perf_counter()
        result = asyncio.run(
            run_providers_with_quorum(
                providers, "q", "s", _policy(), provider_policy_lookup=lookup,
                similarity_fn=_similarity_fn,
            )
        )
        elapsed = time.perf_counter() - started

        # Raw quorum (2 LIVE) never satisfied without the core provider, so
        # the bounded disagreement wait never starts -- the loop waits for
        # prov-z (the core one) to finish normally, exactly as before.
        assert elapsed >= GEMINI_FAIL_DELAY * 1.2 * 0.8
        assert result.early_synthesis is False
        assert result.late_tasks == {}
        assert result.disagreement_wait_actual_ms == 0


class TestFOnlyOneLiveNoForcedProceed:
    def test_no_forced_proceed_with_a_single_live_response(self):
        providers = [
            _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A),
            _TimedProvider("model-e", MISTRAL_DELAY, outcome="failed"),
            _TimedProvider("model-c", GEMINI_FAIL_DELAY, outcome="failed"),
        ]
        result = asyncio.run(
            run_providers_with_quorum(
                providers, "q", "s", _policy(), similarity_fn=_similarity_fn,
            )
        )
        assert result.early_synthesis is False
        assert result.late_tasks == {}
        assert result.disagreement_wait_actual_ms == 0
        assert set(result.finalized.keys()) == {"model-a", "model-e", "model-c"}
        assert result.finalized["model-a"].provider_status == "LIVE"


class TestGLateProviderNeverCancelled:
    def test_pending_task_not_cancelled_after_forced_proceed(self):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_VERY_SLOW_DELAY, text="gemini answer")

            result = await run_providers_with_quorum(
                [openai_p, mistral_p, gemini_p], "q", "s",
                _policy(), similarity_fn=_similarity_fn,
            )
            late_task = result.late_tasks["model-c"]
            assert not late_task.cancelled()
            assert not late_task.done()
            await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)
            assert not late_task.cancelled()
            assert late_task.done()
            assert late_task.exception() is None

        asyncio.run(scenario())


class TestJNoTaskLeak:
    def test_background_task_referenced_then_cleaned_up(self):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_VERY_SLOW_DELAY, text="gemini answer")

            before = set(_BACKGROUND_TASKS)
            result = await run_providers_with_quorum(
                [openai_p, mistral_p, gemini_p], "q", "s",
                _policy(), similarity_fn=_similarity_fn,
            )
            late_task = result.late_tasks["model-c"]
            assert late_task in _BACKGROUND_TASKS
            assert late_task not in before

            await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)
            assert late_task not in _BACKGROUND_TASKS

        asyncio.run(scenario())


class TestKThreeFastProvidersNoRegression:
    def test_three_fast_providers_no_disagreement_wait_no_extra_latency(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", OPENAI_DELAY, text=SIMILAR_A),
                _TimedProvider("model-c", OPENAI_DELAY * 1.1, text=SIMILAR_B),
                _TimedProvider("model-e", OPENAI_DELAY * 1.2, text=SIMILAR_A),
            ]
            started = time.perf_counter()
            result = await run_providers_with_quorum(
                providers, "q", "s", _policy(), similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            assert result.late_tasks == {}
            assert result.early_synthesis is False
            assert result.disagreement_wait_actual_ms == 0
            assert set(result.finalized.keys()) == {"model-a", "model-c", "model-e"}
            # All three resolve well before any wait/grace window could add
            # meaningful delay.
            assert elapsed < WAIT_SECONDS

        asyncio.run(scenario())


class TestLZeroDisagreementWait:
    def test_zero_wait_proceeds_immediately_after_gate_failure(self):
        async def scenario():
            openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
            mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
            gemini_p = _TimedProvider("model-c", GEMINI_VERY_SLOW_DELAY, text="irrelevant")

            started = time.perf_counter()
            result = await run_providers_with_quorum(
                [openai_p, mistral_p, gemini_p], "q", "s",
                _policy(disagreement_wait_seconds=0.0), similarity_fn=_similarity_fn,
            )
            elapsed = time.perf_counter() - started

            assert result.early_synthesis is True
            assert set(result.finalized.keys()) == {"model-a", "model-e"}
            assert set(result.late_tasks.keys()) == {"model-c"}
            # Proceeded right after raw quorum + failed gate were detected,
            # nowhere close to Gemini's own delay.
            assert elapsed < GEMINI_VERY_SLOW_DELAY * 0.3

            await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)

        asyncio.run(scenario())


# ==========================================================================
# 2) Integration-level: server.compare_query end to end (FakeDB, no HTTP).
# ==========================================================================

class TestHILateResultPersistedSuperAnswerNotRegenerated:
    def _seed_query(self, fake_db, query_id="q-bounded-wait"):
        fake_db["queries"].items = [{
            "id": query_id,
            "prompt": "What is the latest news today about this topic?",
            "strategy": "balanced",
            "audience": "professional",
            "format": "paragraph",
            "answer_language": "en",
        }]

    def test_late_gemini_result_persisted_super_answer_unchanged(self, fake_db, monkeypatch):
        query_id = "q-bounded-wait"
        self._seed_query(fake_db, query_id)
        monkeypatch.setattr(
            server, "DEFAULT_QUORUM_POLICY",
            _policy(grace_window_seconds=0.02),
        )
        openai_p = _TimedProvider("model-a", OPENAI_DELAY, text=DISSIMILAR_A)
        mistral_p = _TimedProvider("model-e", MISTRAL_DELAY, text=DISSIMILAR_B)
        gemini_p = _TimedProvider("model-c", GEMINI_VERY_SLOW_DELAY, text="Gemini answer")

        mocked_synth_instance = SimpleNamespace(
            available=True, synthesize=AsyncMock(return_value=_synth_payload()),
        )

        async def scenario():
            with patch.object(server, "providers_for_execution", return_value=("LIVE", [openai_p, mistral_p, gemini_p])), \
                 patch.object(server, "Synthesizer", return_value=mocked_synth_instance) as mocked_synth_cls:
                started = time.perf_counter()
                response = await server.compare_query(query_id, _anonymous_identity())
                elapsed = time.perf_counter() - started

                # The HTTP response did not wait for Gemini's very slow delay.
                assert elapsed < GEMINI_VERY_SLOW_DELAY * 0.5
                assert {r.id for r in response.responses} == {"model-a", "model-e"}
                assert response.trusted_conclusion == "Synthesized answer."
                assert mocked_synth_cls.call_count == 1

                # Let the late Gemini task (and its persistence follow-up)
                # complete, in the same event loop.
                await asyncio.sleep(GEMINI_VERY_SLOW_DELAY)

                # Super Answer (already returned) is untouched -- no second
                # synthesis was ever triggered by the late arrival (item I).
                assert response.trusted_conclusion == "Synthesized answer."
                assert {r.id for r in response.responses} == {"model-a", "model-e"}
                assert mocked_synth_cls.call_count == 1
                mocked_synth_instance.synthesize.assert_awaited_once()

                # The late provider's real result is now persisted (item H).
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

        asyncio.run(scenario())
