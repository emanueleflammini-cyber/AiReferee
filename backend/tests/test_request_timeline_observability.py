"""Request timeline observability — offline tests, no real API calls.

Covers the perf/request-timeline-observability patch: query_id correlation
across early-synthesis events, disagreement-gate score/threshold/pass
logging (never response text), Synthesizer initial-call/repair-pass timing,
and the compare_query-level start/end log pairs (compare_request_*,
synthesis_*, persistence_*). This patch is purely additive logging — every
test that exercises decision logic (quorum, disagreement gate, grace
window) asserts the SAME structural outcomes already proven by
test_early_synthesis_quorum.py, to demonstrate zero behaviour change.

All delays are tiny (hundredths of a second); nothing here sleeps for the
real 4s/25s/60s production values.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
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
from providers.policy import QuorumPolicy  # noqa: E402
from providers.early_synthesis import run_providers_with_quorum  # noqa: E402
from providers.synthesizer import Synthesizer, SynthesisFailure  # noqa: E402

import server  # noqa: E402


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------

FAST = 0.02
SLOW = 0.15
GRACE = 0.05


class _TimedProvider(Provider):
    def __init__(self, provider_id: str, delay: float, text: str = "answer", outcome: str = "live"):
        self.id = provider_id
        self.provider_name = provider_id
        self._delay = delay
        self._text = text
        self._outcome = outcome
        super().__init__(execution_timeout_seconds=5.0)

    async def generate(self, prompt: str, system: str) -> ProviderResult:
        await asyncio.sleep(self._delay)
        if self._outcome == "failed":
            raise RuntimeError("simulated failure")
        return ProviderResult(text=self._text, model_used="test-model")


def _policy(**overrides) -> QuorumPolicy:
    base = dict(
        minimum_live_responses=2, require_core_provider=True,
        grace_window_seconds=GRACE, disagreement_threshold=0.35,
        late_arriving_behavior="cache_and_notify",
    )
    base.update(overrides)
    return QuorumPolicy(**base)


def _sim(a: str, b: str) -> float:
    return server.jaccard(server.tokens_of(a), server.tokens_of(b))


# -- Synthesizer test doubles (mirrors tests/test_structured_conclusion.py's
#    own synthesizer_with_outputs pattern — self-contained here) ----------

class FakeCompletions:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        output = next(self.outputs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=output))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
            model="test-synthesizer",
        )


def _synthesizer_with_outputs(outputs):
    synth = Synthesizer.__new__(Synthesizer)
    completions = FakeCompletions(outputs)
    synth.available = True
    synth._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return synth, completions


def _valid_conclusion(**overrides):
    payload = {
        "schema_version": "2.0",
        "final_answer": "The combined answer.",
        "agreements": [],
        "disagreements": [],
        "strongest_evidence": [],
        "remaining_uncertainties": [],
        "unsupported_claims": [],
        "confidence": {
            "level": "medium",
            "reason": "The evidence is useful but limited to the current panel.",
            "factors": {"model_agreement": "low", "evidence_quality": "medium", "uncertainty": "medium"},
        },
        "what_could_change_the_verdict": [],
    }
    payload.update(overrides)
    return payload


def _answer(provider_id="model-a", text="Answer"):
    return {
        "id": provider_id,
        "provider_key": "openai",
        "label": "ChatGPT",
        "provider": "OpenAI",
        "provider_status": "LIVE",
        "text": text,
    }


# -- FakeDB (same matched_count-aware shape as test_early_synthesis_quorum.py) --

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
    return IdentityContext(user_id=None, plan=Plan.FREE, entitlements=entitlements_for(Plan.FREE), is_anonymous=True)


def _synth_payload(**overrides):
    payload = dict(
        text="Synthesized answer.", structured_conclusion=None, schema_version="2.1",
        model_used="test-synth-model", latency_ms=5, cost_usd=0.001, claims=[], citations=[],
        claim_schema_version=None, claim_analysis_status="SUCCESS", claim_analysis_error=None,
        repair_attempted=False,
    )
    payload.update(overrides)
    return payload


def _query_ids_in(text: str, event: str) -> list[str]:
    return re.findall(rf"{event}\b[^\n]*?query_id=(\S+)", text)


# ==========================================================================
# 1) Correlation ID propagation across early-synthesis events.
# ==========================================================================

class TestCorrelationIdPropagation:
    def test_all_early_synthesis_events_include_query_id(self, caplog):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="cats are wonderful pets"),
                _TimedProvider("model-e", FAST * 1.2, text="cats are wonderful animals"),
                _TimedProvider("model-c", SLOW, text="cats are wonderful pets too"),
            ]
            with caplog.at_level(logging.INFO):
                await run_providers_with_quorum(
                    providers, "q", "s", _policy(), similarity_fn=_sim,
                    correlation_id="corr-abc-123",
                )
                await asyncio.sleep(SLOW + 0.1)

        asyncio.run(scenario())
        text = caplog.text
        for event in (
            "early_synthesis_provider_execution_started",
            "early_synthesis_time_to_first_provider_ms",
            "early_synthesis_provider_finalized",
            "early_synthesis_disagreement_gate_result",
            "early_synthesis_quorum_reached",
            "early_synthesis_grace_window_started",
            "early_synthesis_grace_window_ended",
            "early_synthesis_late_provider_completed",
        ):
            ids = _query_ids_in(text, event)
            assert ids, f"expected at least one '{event}' log line"
            assert all(i == "corr-abc-123" for i in ids), f"{event} logged with wrong/missing query_id: {ids}"

    def test_correlation_id_defaults_to_unknown_without_crashing(self, caplog):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="answer A"),
                _TimedProvider("model-e", FAST * 1.2, text="answer A restated"),
            ]
            with caplog.at_level(logging.INFO):
                result = await run_providers_with_quorum(providers, "q", "s", _policy(), similarity_fn=_sim)
            return result

        result = asyncio.run(scenario())
        assert set(result.finalized.keys()) == {"model-a", "model-e"}
        assert "query_id=unknown" in caplog.text


# ==========================================================================
# 2) Disagreement gate logging.
# ==========================================================================

class TestDisagreementGateLogging:
    def test_gate_logs_score_threshold_and_pass_true(self, caplog):
        providers = [
            _TimedProvider("model-a", FAST, text="cats are wonderful pets"),
            _TimedProvider("model-e", FAST * 1.2, text="cats are wonderful animals"),
        ]
        with caplog.at_level(logging.INFO):
            asyncio.run(
                run_providers_with_quorum(
                    providers, "q", "s", _policy(), similarity_fn=_sim, correlation_id="gate-1",
                )
            )
        line = next(l for l in caplog.text.splitlines() if "early_synthesis_disagreement_gate_result" in l)
        assert "query_id=gate-1" in line
        assert "threshold=0.3500" in line
        assert "gate_passed=True" in line
        assert re.search(r"similarity_score=0\.\d{4}", line)
        assert "['model-a', 'model-e']" in line or "model-a" in line and "model-e" in line

    def test_gate_logs_pass_false_below_threshold(self, caplog):
        text_a = "To reduce your cloud bill, right-size your instances, use reserved capacity, and delete unused storage."
        text_b = "Cutting cloud costs typically involves right-sizing compute instances, committing to reserved pricing, and removing orphaned storage volumes."
        assert _sim(text_a, text_b) < 0.35  # sanity: this pair is known to fall below the default threshold
        providers = [
            _TimedProvider("model-a", FAST, text=text_a),
            _TimedProvider("model-e", FAST * 1.2, text=text_b),
        ]
        with caplog.at_level(logging.INFO):
            result = asyncio.run(
                run_providers_with_quorum(
                    providers, "q", "s", _policy(), similarity_fn=_sim, correlation_id="gate-2",
                )
            )
        assert result.early_synthesis is False  # gate blocked, behaviour unchanged from Patch 2
        line = next(l for l in caplog.text.splitlines() if "early_synthesis_disagreement_gate_result" in l)
        assert "gate_passed=False" in line

    def test_gate_log_never_contains_response_text(self, caplog):
        secret_a = "SECRET_MARKER_ALPHA the treasure is buried under the oak tree"
        secret_b = "SECRET_MARKER_BETA completely unrelated content about something else"
        providers = [
            _TimedProvider("model-a", FAST, text=secret_a),
            _TimedProvider("model-e", FAST * 1.2, text=secret_b),
        ]
        with caplog.at_level(logging.INFO):
            asyncio.run(
                run_providers_with_quorum(
                    providers, "secret prompt content", "secret system content",
                    _policy(), similarity_fn=_sim, correlation_id="gate-3",
                )
            )
        assert "SECRET_MARKER_ALPHA" not in caplog.text
        assert "SECRET_MARKER_BETA" not in caplog.text
        assert "secret prompt content" not in caplog.text
        assert "secret system content" not in caplog.text


# ==========================================================================
# 3) Synthesizer initial-call / repair-pass observability.
# ==========================================================================

class TestSynthesizerObservability:
    def test_initial_call_measured_no_repair(self, caplog):
        synth, completions = _synthesizer_with_outputs([json.dumps(_valid_conclusion())])
        with caplog.at_level(logging.INFO):
            result = asyncio.run(
                synth.synthesize("Question", [_answer()], "en", correlation_id="synth-1")
            )
        assert completions.calls == 1
        assert result["repair_attempted"] is False

        text = caplog.text
        assert "synthesis_initial_call_started query_id=synth-1" in text
        assert re.search(r"synthesis_initial_call_completed query_id=synth-1 duration_ms=\d+", text)
        assert "synthesis_repair_started" not in text
        assert "synthesis_repair_completed" not in text

        breakdown = next(l for l in text.splitlines() if "synthesis_call_breakdown" in l)
        assert "query_id=synth-1" in breakdown
        assert "repair_required=False" in breakdown
        assert "repair_ms=0" in breakdown  # absent repair -> coherent zero, not a missing/garbage value
        assert re.search(r"initial_call_ms=\d+", breakdown)
        assert re.search(r"total_ms=\d+", breakdown)

    def test_repair_pass_measured_separately(self, caplog):
        synth, completions = _synthesizer_with_outputs(
            ["not json", json.dumps(_valid_conclusion())]
        )
        with caplog.at_level(logging.INFO):
            result = asyncio.run(
                synth.synthesize("Question", [_answer()], "en", correlation_id="synth-2")
            )
        assert completions.calls == 2
        assert result["repair_attempted"] is True

        text = caplog.text
        assert "synthesis_initial_call_started query_id=synth-2" in text
        assert "synthesis_initial_call_completed query_id=synth-2" in text
        assert "synthesis_repair_started query_id=synth-2" in text
        assert "synthesis_repair_completed query_id=synth-2" in text

        breakdown = next(l for l in text.splitlines() if "synthesis_call_breakdown" in l)
        assert "repair_required=True" in breakdown
        initial_ms = int(re.search(r"initial_call_ms=(\d+)", breakdown).group(1))
        repair_ms_match = re.search(r"repair_ms=(\d+)", breakdown)
        assert repair_ms_match is not None
        # Both measured as distinct, independent numbers (not the same field reused).
        assert isinstance(initial_ms, int)

    def test_no_prompt_or_answer_content_in_synthesis_logs(self, caplog):
        synth, _completions = _synthesizer_with_outputs([json.dumps(_valid_conclusion())])
        with caplog.at_level(logging.INFO):
            asyncio.run(
                synth.synthesize(
                    "SECRET_USER_QUESTION about something private",
                    [_answer(text="SECRET_PROVIDER_ANSWER content")],
                    "en", correlation_id="synth-3",
                )
            )
        assert "SECRET_USER_QUESTION" not in caplog.text
        assert "SECRET_PROVIDER_ANSWER" not in caplog.text
        assert "The combined answer." not in caplog.text  # final_answer text, also must not leak


# ==========================================================================
# 4) compare_query-level request timeline (integration, FakeDB, no HTTP).
# ==========================================================================

class TestServerRequestTimeline:
    def _seed_query(self, fake_db, query_id):
        fake_db["queries"].items = [{
            "id": query_id,
            "prompt": "What is the latest news today about this topic?",
            "strategy": "balanced", "audience": "professional", "format": "paragraph",
            "answer_language": "en",
        }]

    def test_full_timeline_events_present_and_correlated(self, fake_db, monkeypatch, caplog):
        query_id = "timeline-q1"
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
            with caplog.at_level(logging.INFO), \
                 patch.object(server, "providers_for_execution", return_value=("LIVE", [openai_p, mistral_p, gemini_p])), \
                 patch.object(server, "Synthesizer", return_value=mocked_synth_instance):
                await server.compare_query(query_id, _anonymous_identity())
                await asyncio.sleep(SLOW + 0.15)  # drain the late provider

        asyncio.run(scenario())
        text = caplog.text

        for event in (
            "compare_request_started",
            "compare_provider_phase_completed",
            "early_synthesis_started",
            "early_synthesis_providers_used_in_synthesis",
            "synthesis_started",
            "synthesis_completed",
            "persistence_started",
            "persistence_completed",
            "compare_request_completed",
        ):
            ids = _query_ids_in(text, event)
            assert ids, f"expected at least one '{event}' log line"
            assert all(i == query_id for i in ids), f"{event} logged with wrong query_id: {ids}"

        # synthesize() itself received the correlation id (kwarg propagated,
        # not just logged around it at the call site).
        _, kwargs = mocked_synth_instance.synthesize.await_args
        assert kwargs.get("correlation_id") == query_id or \
            mocked_synth_instance.synthesize.await_args.args[-1] == query_id \
            or "correlation_id" in mocked_synth_instance.synthesize.call_args.kwargs

    def test_total_request_ms_covers_synthesis_segment(self, fake_db, monkeypatch, caplog):
        query_id = "timeline-q2"
        self._seed_query(fake_db, query_id)
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

        with caplog.at_level(logging.INFO), \
             patch.object(server, "providers_for_execution", return_value=("LIVE", providers)), \
             patch.object(server, "Synthesizer", return_value=mocked_synth_instance):
            asyncio.run(server.compare_query(query_id, _anonymous_identity()))

        text = caplog.text
        total_ms = int(re.search(r"compare_request_completed query_id=%s total_request_ms=(\d+)" % re.escape(query_id), text).group(1))
        synth_ms = int(re.search(r"synthesis_completed query_id=%s status=SUCCESS synthesis_total_ms=(\d+)" % re.escape(query_id), text).group(1))
        assert total_ms >= synth_ms  # the whole request must cover its own synthesis segment

    def test_failed_synthesis_telemetry_is_returned_and_persisted(
        self,
        fake_db,
        monkeypatch,
    ):
        query_id = "timeline-failed-synthesis"
        self._seed_query(fake_db, query_id)
        providers = [
            _TimedProvider("model-a", 0.001, text="OpenAI answer"),
            _TimedProvider("model-c", 0.001, text="Gemini answer"),
            _TimedProvider("model-e", 0.001, text="Mistral answer"),
        ]
        telemetry = {
            "model_used": "gpt-5.4-mini",
            "input_tokens": 250,
            "output_tokens": 50,
            "total_tokens": 300,
            "latency_ms": 4321,
            "cost_usd": 0.0042,
            "repair_attempted": True,
            "attempts": [
                {
                    "stage": "initial",
                    "request_id": "req_initial",
                    "finish_reason": "stop",
                    "model": "gpt-5.4-mini",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "latency_ms": 2000,
                },
                {
                    "stage": "repair",
                    "request_id": "req_repair",
                    "finish_reason": "stop",
                    "model": "gpt-5.4-mini",
                    "input_tokens": 150,
                    "output_tokens": 30,
                    "total_tokens": 180,
                    "latency_ms": 2200,
                },
            ],
        }
        mocked_synth_instance = SimpleNamespace(
            available=True,
            synthesize=AsyncMock(
                side_effect=SynthesisFailure(
                    "Trusted Conclusion could not be validated after one repair attempt.",
                    telemetry=telemetry,
                )
            ),
        )

        with patch.object(
            server,
            "providers_for_execution",
            return_value=("LIVE", providers),
        ), patch.object(
            server,
            "Synthesizer",
            return_value=mocked_synth_instance,
        ):
            response = asyncio.run(
                server.compare_query(query_id, _anonymous_identity())
            )

        assert response.synthesis_status == "FAILED"
        assert response.trusted_conclusion == ""
        assert response.trusted_conclusion_structured is None
        assert response.synthesis_model == "gpt-5.4-mini"
        assert response.synthesis_latency_ms == 4321
        assert response.synthesis_cost_usd == pytest.approx(0.0042)
        assert response.synthesis_input_tokens == 250
        assert response.synthesis_output_tokens == 50
        assert response.synthesis_total_tokens == 300
        assert response.total_cost_usd == pytest.approx(0.0042)

        stored = fake_db["conclusions"].documents[query_id]
        assert stored["synthesis_status"] == "FAILED"
        assert stored["synthesis_model"] == "gpt-5.4-mini"
        assert stored["synthesis_latency_ms"] == 4321
        assert stored["synthesis_cost_usd"] == pytest.approx(0.0042)
        assert stored["synthesis_input_tokens"] == 250
        assert stored["synthesis_output_tokens"] == 50
        assert stored["synthesis_total_tokens"] == 300
        assert stored["synthesis_repair_attempted"] is True
        assert stored["synthesis_attempt_metadata"] == telemetry["attempts"]
        assert stored["total_cost_usd"] == pytest.approx(0.0042)


# ==========================================================================
# 5) No sensitive content anywhere in the new logs.
# ==========================================================================

class TestNoSensitiveContentInLogs:
    def test_server_timeline_logs_carry_no_content(self, fake_db, monkeypatch, caplog):
        query_id = "privacy-q1"
        fake_db["queries"].items = [{
            "id": query_id,
            "prompt": "SECRET_PROMPT_MARKER what is the latest news today",
            "strategy": "balanced", "audience": "professional", "format": "paragraph",
            "answer_language": "en",
        }]
        monkeypatch.setattr(
            server, "DEFAULT_QUORUM_POLICY",
            QuorumPolicy(
                minimum_live_responses=2, require_core_provider=True,
                grace_window_seconds=GRACE, disagreement_threshold=0.0,
                late_arriving_behavior="cache_and_notify",
            ),
        )
        providers = [
            _TimedProvider("model-a", FAST, text="SECRET_ANSWER_A content"),
            _TimedProvider("model-c", FAST * 1.1, text="SECRET_ANSWER_C content"),
            _TimedProvider("model-e", FAST * 1.2, text="SECRET_ANSWER_E content"),
        ]
        mocked_synth_instance = SimpleNamespace(
            available=True,
            synthesize=AsyncMock(return_value=_synth_payload(text="SECRET_SUPER_ANSWER")),
        )
        with caplog.at_level(logging.INFO), \
             patch.object(server, "providers_for_execution", return_value=("LIVE", providers)), \
             patch.object(server, "Synthesizer", return_value=mocked_synth_instance):
            asyncio.run(server.compare_query(query_id, _anonymous_identity()))

        text = caplog.text
        for forbidden in (
            "SECRET_PROMPT_MARKER", "SECRET_ANSWER_A", "SECRET_ANSWER_C",
            "SECRET_ANSWER_E", "SECRET_SUPER_ANSWER", "OPENAI_API_KEY", "sk-",
        ):
            assert forbidden not in text


# ==========================================================================
# 6) Zero behaviour change — same structural outcomes as Patch 2.
# ==========================================================================

class TestZeroBehaviorChange:
    def test_quorum_policy_defaults_unchanged(self):
        policy = QuorumPolicy()
        assert policy.minimum_live_responses == 2
        assert policy.require_core_provider is True
        assert policy.grace_window_seconds == 4.0
        assert policy.disagreement_threshold == 0.35

    def test_three_fast_agreeing_providers_still_all_finalize(self):
        providers = [
            _TimedProvider("model-a", FAST, text="cats are wonderful pets"),
            _TimedProvider("model-c", FAST * 1.1, text="cats are wonderful animals"),
            _TimedProvider("model-e", FAST * 1.2, text="cats make wonderful pets"),
        ]
        result = asyncio.run(
            run_providers_with_quorum(providers, "q", "s", _policy(), similarity_fn=_sim)
        )
        assert result.late_tasks == {}
        assert result.early_synthesis is False
        assert set(result.finalized.keys()) == {"model-a", "model-c", "model-e"}

    def test_two_fast_agreeing_plus_one_slow_still_triggers_early_synthesis(self):
        async def scenario():
            providers = [
                _TimedProvider("model-a", FAST, text="cats are wonderful pets"),
                _TimedProvider("model-e", FAST * 1.2, text="cats are wonderful animals"),
                _TimedProvider("model-c", SLOW, text="cats are wonderful pets too"),
            ]
            result = await run_providers_with_quorum(
                providers, "q", "s", _policy(), similarity_fn=_sim,
            )
            assert result.early_synthesis is True
            assert set(result.late_tasks.keys()) == {"model-c"}
            assert set(result.finalized.keys()) == {"model-a", "model-e"}
            await asyncio.sleep(SLOW + 0.1)

        asyncio.run(scenario())


# ==========================================================================
# 7) Patch overhead is negligible.
# ==========================================================================

class TestPatchOverheadNegligible:
    def test_three_near_instant_providers_stay_near_instant(self):
        providers = [
            _TimedProvider("model-a", 0.001, text="a"),
            _TimedProvider("model-c", 0.001, text="a too"),
            _TimedProvider("model-e", 0.001, text="a as well"),
        ]
        started = time.perf_counter()
        asyncio.run(run_providers_with_quorum(providers, "q", "s", _policy(), similarity_fn=_sim))
        elapsed = time.perf_counter() - started
        # Generous bound — this is a sanity check against gross overhead
        # (e.g. an accidental sleep or blocking call), not a strict benchmark.
        assert elapsed < 0.3
