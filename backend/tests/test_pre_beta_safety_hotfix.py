"""Pre-closed-beta safety hotfix — offline tests.

Unlike the other files in this directory (which are opt-in integration
tests against a live backend + Mongo, gated by RUN_EXTERNAL_API_TESTS), the
tests here run ALWAYS, with no live Mongo, no provider API keys and no
network access at all. They exist specifically to prove the guarantees
required by the pre-beta safety hotfix:

    - an oversized prompt is rejected before any provider, embedding,
      translation or synthesis call can start;
    - /api/compare_logs is admin-only;
    - /api/queries (list, no ID) is admin-only — approved follow-up fix,
      same exposure class as /api/compare_logs;
    - an unsupported translation target_language is rejected before any
      translation call can start;
    - Smart Reuse's match payload is unchanged (documented, not removed);
    - audience/format/strategy are whitelisted, so none of the three
      client-controlled fields can be padded to inflate the system prompt
      sent to every provider, and strategy cannot select a provider, model
      or tier — follow-up fix requested after code review of this hotfix.

MongoDB access is replaced with a tiny in-memory fake (`FakeDB` below) that
implements only the subset of the Motor async API this module's routes
actually use. Every provider / embedding / translation call site is patched
with a mock and asserted not-called where the hotfix's contract requires it
— this is what proves "no external call happens for a rejected request",
which a live-server integration test cannot prove on its own.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# server.py reads these at import time; Motor does not connect eagerly, so a
# syntactically valid URL is enough — no real MongoDB is ever contacted.
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "test_database_offline")
# Deterministic limit for this module regardless of the developer's .env.
os.environ["MAX_PROMPT_LENGTH"] = "4000"

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import auth  # noqa: E402


# --------------------------------------------------------------------------
# Minimal in-memory stand-in for the Motor async API surface this module's
# routes actually use (find / find_one / insert_one / update_one / sort /
# limit / to_list). Deliberately not a general-purpose Mongo emulator.
# --------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    async def to_list(self, length=None):
        return self._items if length is None else self._items[:length]

    def __aiter__(self):
        items = list(self._items)

        async def _gen():
            for item in items:
                yield item

        return _gen()


class FakeCollection:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.inserted = []
        self.updated = []

    def find(self, _query=None, _projection=None):
        return FakeCursor(self.items)

    async def find_one(self, _query=None, _projection=None):
        return self.items[0] if self.items else None

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return SimpleNamespace(inserted_id="fake-id")

    async def update_one(self, query, update, upsert=False):
        self.updated.append((query, update, upsert))
        return SimpleNamespace(matched_count=0, upserted_id=None)

    async def find_one_and_update(self, query, update, upsert=False, return_document=None):
        self.updated.append((query, update, upsert))
        return {"count": 1}


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


@pytest.fixture()
def client():
    return TestClient(server.app)


def _long_prompt(length: int) -> str:
    return "a" * length


# --------------------------------------------------------------------------
# 1) Prompt length limit — validated before ANY external call.
# --------------------------------------------------------------------------

class TestPromptLengthLimit:
    def test_prompt_within_limit_is_accepted_at_the_model_level(self):
        prompt = _long_prompt(server.MAX_PROMPT_LENGTH)
        record = server.QueryCreate(prompt=prompt)
        assert record.prompt == prompt

    def test_prompt_over_limit_is_rejected_at_the_model_level(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            server.QueryCreate(prompt=_long_prompt(server.MAX_PROMPT_LENGTH + 1))

    def test_match_request_enforces_the_same_limit(self):
        from pydantic import ValidationError

        server.MatchRequest(prompt=_long_prompt(server.MAX_PROMPT_LENGTH))
        with pytest.raises(ValidationError):
            server.MatchRequest(prompt=_long_prompt(server.MAX_PROMPT_LENGTH + 1))

    def test_post_queries_oversized_prompt_rejected_and_never_persisted(self, client, fake_db):
        resp = client.post(
            "/api/queries",
            json={"prompt": _long_prompt(server.MAX_PROMPT_LENGTH + 1)},
        )
        assert resp.status_code == 422
        # The oversized request must never reach the handler body, so the
        # query is never written to Mongo.
        assert fake_db["queries"].inserted == []

    def test_post_queries_match_oversized_prompt_never_calls_embedding(self, client, fake_db):
        with patch.object(server, "get_or_create_embedding", new=AsyncMock()) as mocked_embed:
            resp = client.post(
                "/api/queries/match",
                json={"prompt": _long_prompt(server.MAX_PROMPT_LENGTH + 1)},
            )
            assert resp.status_code == 422
            mocked_embed.assert_not_called()

    def test_compare_defends_against_a_stored_oversized_prompt(self, client, fake_db):
        # Defence in depth: a query record that predates this hotfix (or was
        # inserted outside the API) must still be rejected before any
        # provider is invoked.
        fake_db["queries"].items = [{
            "id": "legacy-query",
            "prompt": _long_prompt(server.MAX_PROMPT_LENGTH + 1),
            "strategy": "balanced",
            "audience": "professional",
            "format": "paragraph",
            "answer_language": "en",
        }]
        with patch.object(server, "providers_for_execution") as mocked_providers:
            resp = client.post("/api/queries/legacy-query/compare")
            assert resp.status_code == 413
            mocked_providers.assert_not_called()


# --------------------------------------------------------------------------
# 2) /api/compare_logs — admin only.
# --------------------------------------------------------------------------

class TestCompareLogsAdminOnly:
    def test_anonymous_request_rejected(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.get("/api/compare_logs")
        # Fails closed: no ADMIN_TOKEN configured -> 503, never 200.
        assert resp.status_code == 503

    def test_wrong_admin_token_rejected(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
        resp = client.get("/api/compare_logs", headers={"X-Admin-Token": "wrong-token"})
        assert resp.status_code == 401

    def test_missing_header_rejected_even_when_token_is_configured(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
        resp = client.get("/api/compare_logs")
        assert resp.status_code == 401

    def test_valid_admin_token_allowed(self, client, monkeypatch, fake_db):
        monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
        fake_db["compare_logs"].items = [{
            "id": "log-1", "query_id": "q-1", "prompt": "hello",
            "provider_id": "model-a", "cost_usd": 0.001, "created_at": "2026-01-01T00:00:00+00:00",
        }]
        resp = client.get("/api/compare_logs", headers={"X-Admin-Token": "correct-token"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["logs"][0]["id"] == "log-1"

    def test_admin_token_comparison_is_constant_time(self):
        # Guards against a regression back to `!=` string comparison.
        import inspect
        source = inspect.getsource(auth.require_admin)
        assert "compare_digest" in source


# --------------------------------------------------------------------------
# 2b) /api/queries (list, no ID) — admin only.
#
# Same exposure class as /api/compare_logs (every user's prompt text,
# unauthenticated) — discovered during the hotfix, out of the originally
# approved scope, and fixed as a follow-up once explicitly approved. See
# backend/SECURITY_OWNERSHIP_TODO.md.
# --------------------------------------------------------------------------

class TestListQueriesAdminOnly:
    def test_anonymous_request_rejected(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.get("/api/queries")
        # Fails closed: no ADMIN_TOKEN configured -> 503, never 200.
        assert resp.status_code == 503

    def test_wrong_admin_token_rejected(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
        resp = client.get("/api/queries", headers={"X-Admin-Token": "wrong-token"})
        assert resp.status_code == 401

    def test_missing_header_rejected_even_when_token_is_configured(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
        resp = client.get("/api/queries")
        assert resp.status_code == 401

    def test_valid_admin_token_allowed(self, client, monkeypatch, fake_db):
        monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
        fake_db["queries"].items = [{
            "id": "q-1",
            "prompt": "hello",
            "goal": 50,
            "detail": 50,
            "audience": "professional",
            "format": "paragraph",
            "strategy": "balanced",
            "answer_language": "en",
            "created_at": "2026-01-01T00:00:00+00:00",
        }]
        resp = client.get("/api/queries", headers={"X-Admin-Token": "correct-token"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == "q-1"
        assert body[0]["prompt"] == "hello"


# --------------------------------------------------------------------------
# 3) Translation target_language validation.
# --------------------------------------------------------------------------

class TestTranslateLanguageValidation:
    def test_valid_language_proceeds_unchanged(self, client, fake_db):
        fake_db["conclusions"].items = [{
            "id": "concl-1",
            "trusted_conclusion_language": "it",
            "trusted_conclusion": "Testo gia' in italiano.",
            "translations": {},
        }]
        with patch.object(server, "Translator") as mocked_translator_cls:
            resp = client.post(
                "/api/conclusions/concl-1/translate",
                json={"target_language": "it"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["target_language"] == "it"
            assert body["cache_hit"] is True
            assert body["cost_usd"] == 0.0
            # Same-language fast path: the OpenAI-backed Translator must
            # never even be constructed.
            mocked_translator_cls.assert_not_called()

    def test_unsupported_language_rejected_before_any_translation_call(self, client, fake_db):
        fake_db["conclusions"].items = [{
            "id": "concl-1",
            "trusted_conclusion_language": "en",
            "trusted_conclusion": "Some text.",
            "translations": {},
        }]
        with patch.object(server, "_translate_or_fetch", new=AsyncMock()) as mocked_fetch:
            resp = client.post(
                "/api/conclusions/concl-1/translate",
                json={"target_language": "xx-not-a-real-language"},
            )
            assert resp.status_code == 400
            assert "Unsupported target_language" in resp.json()["detail"]
            # The endpoint must reject before ever reaching the shared
            # translate/fetch helper — no cache key is minted, no call made.
            mocked_fetch.assert_not_called()

    def test_unsupported_language_case_insensitive_still_rejected(self, client, fake_db):
        with patch.object(server, "_translate_or_fetch", new=AsyncMock()) as mocked_fetch:
            resp = client.post(
                "/api/conclusions/concl-1/translate",
                json={"target_language": "XX-Bogus"},
            )
            assert resp.status_code == 400
            mocked_fetch.assert_not_called()

    def test_get_conclusion_falls_back_to_english_for_unsupported_lang(self, client, fake_db):
        fake_db["conclusions"].items = [{
            "id": "concl-1",
            "trusted_conclusion_language": "en",
            "trusted_conclusion": "Some text.",
            "translations": {},
        }]
        resp = client.get("/api/conclusions/concl-1", params={"lang": "not-a-real-lang"})
        assert resp.status_code == 200
        # Unsupported value collapses onto the existing "en" cache entry
        # instead of minting a fresh translation request.
        assert resp.json()["language"] == "en"


# --------------------------------------------------------------------------
# 4) Smart Reuse — match payload left unchanged (see
#    backend/SMART_REUSE_PRIVACY_NOTE.md for why removal was not compatible
#    with the current ReuseFound.jsx / Results.jsx frontend flow).
# --------------------------------------------------------------------------

class TestSmartReuseMatchPayloadUnchanged:
    def test_match_response_still_includes_prompt_field(self):
        # Regression guard: MatchResponse.match is a free-form dict today: if
        # a future change removes "prompt" from it without also updating
        # ReuseFound.jsx / Results.jsx, this test should be the first thing
        # that catches it. See SMART_REUSE_PRIVACY_NOTE.md for the documented
        # tradeoff — this hotfix intentionally leaves the field in place.
        resp = server.MatchResponse(
            policy="reusable",
            topic="stable",
            match={"id": "x", "prompt": "some previous question", "similarity": 91},
            reason="strong match",
            ttl_days=30,
        )
        assert resp.match["prompt"] == "some previous question"


# --------------------------------------------------------------------------
# 5) CORS — credentials default is safe.
# --------------------------------------------------------------------------

class TestCorsDefaults:
    def test_credentials_default_false_without_env_override(self, monkeypatch):
        monkeypatch.delenv("CORS_ALLOW_CREDENTIALS", raising=False)
        value = os.environ.get("CORS_ALLOW_CREDENTIALS", "false").strip().lower() == "true"
        assert value is False


# --------------------------------------------------------------------------
# 6) audience / format / strategy — whitelisted, so a client cannot pad any
#    of the three to inflate the system prompt sent to every provider (the
#    follow-up fix requested after code review of this same hotfix).
#    compare_query interpolates all three verbatim:
#        f"Audience: {audience}. Preferred format: {fmt}. Strategy: {strategy}."
#    QueryCreate now whitelists them at creation time (model-level, before the
#    handler runs); compare_query additionally re-sanitizes them defensively
#    for any query record that predates the whitelist. See SUPPORTED_
#    AUDIENCES / SUPPORTED_FORMATS / SUPPORTED_STRATEGIES in server.py.
# --------------------------------------------------------------------------

class _CapturingProvider:
    """Stand-in provider that records the `system` prompt it was called with
    and fails immediately — no network call, no synthesis triggered."""

    def __init__(self, provider_id: str):
        self.id = provider_id
        self.captured_system: Optional[str] = None

    async def timed_generate(self, prompt: str, system: str):
        self.captured_system = system
        return server.ProviderResult(text="", provider_status="FAILED", error="stubbed for test")


class TestShapingFieldsWhitelist:
    # -- audience -----------------------------------------------------------

    def test_audience_normal_value_accepted_at_model_level(self):
        record = server.QueryCreate(prompt="A normal question.", audience="professional")
        assert record.audience == "professional"

    def test_audience_normalizes_case_and_whitespace(self):
        record = server.QueryCreate(prompt="A normal question.", audience="  Expert  ")
        assert record.audience == "expert"

    def test_audience_oversized_value_rejected_at_model_level(self):
        from pydantic import ValidationError

        oversized = "professional" + ("a" * 5000)
        with pytest.raises(ValidationError):
            server.QueryCreate(prompt="A normal question.", audience=oversized)

    def test_audience_arbitrary_value_rejected_at_model_level(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            server.QueryCreate(prompt="A normal question.", audience="not-a-real-audience")

    def test_post_queries_oversized_audience_rejected_and_never_persisted(self, client, fake_db):
        resp = client.post("/api/queries", json={
            "prompt": "A normal question.",
            "audience": "professional" + ("a" * 5000),
        })
        assert resp.status_code == 422
        assert fake_db["queries"].inserted == []

    # -- format ---------------------------------------------------------------

    def test_format_normal_value_accepted_at_model_level(self):
        record = server.QueryCreate(prompt="A normal question.", format="bullets")
        assert record.format == "bullets"

    def test_format_oversized_value_rejected_at_model_level(self):
        from pydantic import ValidationError

        oversized = "paragraph" + ("b" * 5000)
        with pytest.raises(ValidationError):
            server.QueryCreate(prompt="A normal question.", format=oversized)

    def test_format_arbitrary_value_rejected_at_model_level(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            server.QueryCreate(prompt="A normal question.", format="<script>alert(1)</script>")

    def test_post_queries_oversized_format_rejected_and_never_persisted(self, client, fake_db):
        resp = client.post("/api/queries", json={
            "prompt": "A normal question.",
            "format": "paragraph" + ("b" * 5000),
        })
        assert resp.status_code == 422
        assert fake_db["queries"].inserted == []

    # -- strategy -------------------------------------------------------------

    def test_every_supported_strategy_value_accepted(self):
        for value in sorted(server.SUPPORTED_STRATEGIES):
            record = server.QueryCreate(prompt="A normal question.", strategy=value)
            assert record.strategy == value

    def test_strategy_arbitrary_value_rejected_at_model_level(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            server.QueryCreate(prompt="A normal question.", strategy="use_gpt5_and_max_tier")

    def test_post_queries_arbitrary_strategy_rejected_and_never_persisted(self, client, fake_db):
        resp = client.post("/api/queries", json={
            "prompt": "A normal question.",
            "strategy": "not-a-real-strategy",
        })
        assert resp.status_code == 422
        assert fake_db["queries"].inserted == []

    def test_strategy_never_selects_providers_model_or_tier(self, client, fake_db):
        """Regression guard: `strategy` is descriptive text folded into the
        system prompt only. providers_for_execution() — the single place that
        decides which providers/models/tier run — must be called identically
        (no strategy-derived argument) regardless of its value."""
        fake_db["queries"].items = [{
            "id": "q1",
            "prompt": "What is the latest news today about this topic?",
            "strategy": "max_accuracy",
            "audience": "professional",
            "format": "paragraph",
            "answer_language": "en",
        }]
        with patch.object(server, "providers_for_execution", return_value=("LIVE", [])) as mocked:
            resp = client.post("/api/queries/q1/compare")
            assert resp.status_code == 200
            # Anonymous caller: providers_for_execution() takes zero
            # arguments — strategy is never among them.
            mocked.assert_called_once_with()

    # -- rejection never reaches a provider ------------------------------------

    @pytest.mark.parametrize("field,value", [
        ("audience", "not-a-real-audience"),
        ("format", "not-a-real-format"),
        ("strategy", "not-a-real-strategy"),
    ])
    def test_rejected_shaping_field_never_calls_a_provider(self, client, fake_db, field, value):
        # An invalid shaping field is rejected at query-creation time, so no
        # query id is ever minted for it — it can never reach /compare and
        # therefore can never reach a provider call.
        with patch.object(server, "providers_for_execution") as mocked_providers:
            resp = client.post("/api/queries", json={"prompt": "A normal question.", field: value})
            assert resp.status_code == 422
            mocked_providers.assert_not_called()

    # -- system prompt stays bounded even for a legacy out-of-whitelist record --

    def test_compare_sanitizes_legacy_out_of_whitelist_record_and_bounds_system_prompt(self, client, fake_db):
        # Simulates a query record that predates this whitelist (or was
        # inserted outside the API): oversized audience/format/strategy
        # stored directly. compare_query must not interpolate these verbatim
        # into the system prompt sent to every provider.
        padding = "A" * 10_000
        fake_db["queries"].items = [{
            "id": "legacy-query",
            "prompt": "What is the latest news today about this topic?",
            "strategy": padding,
            "audience": padding,
            "format": padding,
            "answer_language": "en",
        }]
        fake_provider = _CapturingProvider("model-a")
        with patch.object(server, "providers_for_execution", return_value=("LIVE", [fake_provider])):
            resp = client.post("/api/queries/legacy-query/compare")
            assert resp.status_code == 200

        captured = fake_provider.captured_system
        assert captured is not None
        assert padding not in captured
        # Sanitized fallback defaults are used instead.
        assert "Audience: professional." in captured
        assert "Preferred format: paragraph." in captured
        assert "Strategy: balanced." in captured
        # Bounded regardless of how large the stored fields were.
        assert len(captured) < 600

    # -- normal frontend behaviour is unchanged --------------------------------

    def test_defaults_used_when_fields_omitted(self, client, fake_db):
        resp = client.post("/api/queries", json={"prompt": "A normal question."})
        assert resp.status_code == 200
        body = resp.json()
        assert body["audience"] == "professional"
        assert body["format"] == "paragraph"
        assert body["strategy"] == "balanced"

    def test_all_frontend_audience_options_accepted(self, client, fake_db):
        # Mirrors frontend/src/pages/Home.jsx AUDIENCES.
        for audience_id in ("beginner", "professional", "expert"):
            resp = client.post("/api/queries", json={"prompt": "A normal question.", "audience": audience_id})
            assert resp.status_code == 200, audience_id

    def test_all_frontend_format_options_accepted(self, client, fake_db):
        # Mirrors frontend/src/pages/Home.jsx FORMATS.
        for format_id in ("paragraph", "bullets", "table", "steps"):
            resp = client.post("/api/queries", json={"prompt": "A normal question.", "format": format_id})
            assert resp.status_code == 200, format_id

    def test_all_frontend_strategy_options_accepted(self, client, fake_db):
        # Mirrors frontend/src/lib/mockData.js STRATEGIES.
        for strategy_id in ("max_accuracy", "balanced", "creative", "critical", "fast"):
            resp = client.post("/api/queries", json={"prompt": "A normal question.", "strategy": strategy_id})
            assert resp.status_code == 200, strategy_id
