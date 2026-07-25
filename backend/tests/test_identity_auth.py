"""Iteration 4 — identity/auth wiring tests for AI Referee.

Covers:
    - GET /api/me anonymous vs identified
    - Auto-create in users collection + last_seen_at updates
    - Admin surface: fail-closed / 401 wrong token / 200 correct token / 400 unknown plan
    - Compare endpoint identity-aware: three-provider responses and usage counter,
      premium still excludes Claude when disabled, 429 on rate-limit exhaustion
    - /api/providers still 5 slots, /api/plans still FREE available true, others false
    - Smart Reuse jaccard_fallback threshold from env unchanged
    - No outbound calls to disabled Anthropic/xAI providers
    - services/user_keys.set_user_key refuses when USER_KEY_ENCRYPTION_KEY unset
"""
import os
import sys
import uuid
import time
from pathlib import Path
import pytest
import requests
from pymongo import MongoClient

RUN_EXTERNAL_API_TESTS = (
    os.environ.get("RUN_EXTERNAL_API_TESTS", "false").strip().lower() == "true"
)
pytestmark = pytest.mark.skipif(
    not RUN_EXTERNAL_API_TESTS,
    reason=(
        "External API integration tests are opt-in; set "
        "RUN_EXTERNAL_API_TESTS=true with a configured backend."
    ),
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "http://127.0.0.1:8000",
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_TOKEN = "test-admin-token-DO-NOT-USE-IN-PROD"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="session")
def mongo():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


# ---------------- /api/me ----------------

class TestMe:
    def test_me_anonymous(self, s):
        r = s.get(f"{API}/me", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user_id"] is None
        assert data["is_anonymous"] is True
        assert data["plan"] == "free"
        ents = data["entitlements"]
        assert sorted(ents["allowed_provider_ids"]) == [
            "model-a", "model-c", "model-e"
        ]
        assert ents["daily_compare_limit"] == 20
        assert ents["can_use_own_keys"] is False
        assert ents["priority"] == 0

    def test_me_identified_autocreate_and_last_seen(self, s, mongo):
        uid = f"TEST_me_{uuid.uuid4()}"
        try:
            r = s.get(f"{API}/me", headers={"X-User-Id": uid}, timeout=30)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["user_id"] == uid
            assert data["is_anonymous"] is False
            assert data["plan"] == "free"

            # Verify persistence in `users` collection
            doc1 = mongo["users"].find_one({"id": uid})
            assert doc1 is not None, "user not created in users collection"
            assert doc1["plan"] == "free"
            first_seen = doc1.get("last_seen_at")
            assert first_seen

            # Subsequent call should update last_seen_at
            time.sleep(1.1)
            r2 = s.get(f"{API}/me", headers={"X-User-Id": uid}, timeout=30)
            assert r2.status_code == 200
            doc2 = mongo["users"].find_one({"id": uid})
            assert doc2["last_seen_at"] != first_seen, "last_seen_at not updated"
        finally:
            mongo["users"].delete_one({"id": uid})


# ---------------- Admin surface ----------------

class TestAdminPlan:
    def test_admin_wrong_token_401(self, s):
        uid = f"TEST_admin_{uuid.uuid4()}"
        r = s.post(f"{API}/admin/users/{uid}/plan",
                   json={"plan": "premium"},
                   headers={"X-Admin-Token": "bogus-token"}, timeout=30)
        assert r.status_code == 401, r.text

    def test_admin_missing_token_401(self, s):
        uid = f"TEST_admin_{uuid.uuid4()}"
        r = s.post(f"{API}/admin/users/{uid}/plan",
                   json={"plan": "premium"}, timeout=30)
        assert r.status_code == 401, r.text

    def test_admin_correct_token_promotes(self, s, mongo):
        uid = f"TEST_admin_{uuid.uuid4()}"
        try:
            r = s.post(f"{API}/admin/users/{uid}/plan",
                       json={"plan": "premium"},
                       headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["plan"] == "premium"
            assert body["user_id"] == uid

            # Verify entitlements returned via /api/me for that user
            r2 = s.get(f"{API}/me", headers={"X-User-Id": uid}, timeout=30)
            assert r2.status_code == 200
            data = r2.json()
            assert data["plan"] == "premium"
            ents = data["entitlements"]
            assert len(ents["allowed_provider_ids"]) == 5
            assert ents["daily_compare_limit"] == 200
        finally:
            mongo["users"].delete_one({"id": uid})

    def test_admin_unknown_plan_400(self, s):
        uid = f"TEST_admin_{uuid.uuid4()}"
        r = s.post(f"{API}/admin/users/{uid}/plan",
                   json={"plan": "gold"},
                   headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=30)
        assert r.status_code == 400, r.text


# ---------------- Compare identity-aware ----------------

def _create_query(s, prompt="Explain database transactions briefly"):
    r = s.post(f"{API}/queries", json={
        "prompt": prompt, "goal": 50, "detail": 50,
        "audience": "professional", "format": "paragraph", "strategy": "balanced"
    }, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


class TestCompareIdentity:
    def test_compare_anonymous_three_responses(self, s):
        qid = _create_query(s, "TEST_anon compare simple math sum 2 plus 2")
        r = s.post(f"{API}/queries/{qid}/compare", timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["responses"]) == 3
        ids = {resp["id"] for resp in data["responses"]}
        assert ids == {"model-a", "model-c", "model-e"}, f"unexpected providers: {ids}"
        for resp in data["responses"]:
            assert resp["is_mock"] is False, f"{resp['id']} returned mock"

    def test_compare_free_user_increments_usage(self, s, mongo):
        uid = f"TEST_free_{uuid.uuid4()}"
        try:
            qid = _create_query(s, "TEST_free user compare distinct prompt")
            r = s.post(f"{API}/queries/{qid}/compare",
                       headers={"X-User-Id": uid}, timeout=120)
            assert r.status_code == 200, r.text
            data = r.json()
            assert len(data["responses"]) == 3
            ids = {resp["id"] for resp in data["responses"]}
            assert ids == {"model-a", "model-c", "model-e"}

            # usage_events increments
            from datetime import datetime, timezone
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            ev = mongo["usage_events"].find_one({"user_id": uid, "day": day, "kind": "compare"})
            assert ev is not None
            assert ev["count"] == 1
        finally:
            mongo["users"].delete_one({"id": uid})
            mongo["usage_events"].delete_many({"user_id": uid})

    def test_compare_premium_still_three_because_claude_disabled(self, s, mongo):
        uid = f"TEST_prem_{uuid.uuid4()}"
        try:
            # Promote
            r = s.post(f"{API}/admin/users/{uid}/plan",
                       json={"plan": "premium"},
                       headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=30)
            assert r.status_code == 200

            qid = _create_query(s, "TEST_prem user compare technical question x")
            r = s.post(f"{API}/queries/{qid}/compare",
                       headers={"X-User-Id": uid}, timeout=120)
            assert r.status_code == 200, r.text
            data = r.json()
            # Premium is entitled to Claude but ENABLE_CLAUDE=false -> still 3.
            assert len(data["responses"]) == 3, f"got {len(data['responses'])} responses"
            ids = {resp["id"] for resp in data["responses"]}
            assert "model-b" not in ids, "Claude was called but should be gated by ENABLE_CLAUDE"
            assert ids == {"model-a", "model-c", "model-e"}
        finally:
            mongo["users"].delete_one({"id": uid})
            mongo["usage_events"].delete_many({"user_id": uid})


# ---------------- Rate limit ----------------

class TestRateLimit:
    def test_rate_limit_429_after_20(self, s, mongo):
        uid = f"TEST_rl_{uuid.uuid4()}"
        try:
            # Seed the usage counter at 20 to avoid burning 20 real API calls
            from datetime import datetime, timezone
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            mongo["users"].insert_one({
                "id": uid, "plan": "free",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            })
            mongo["usage_events"].insert_one({
                "user_id": uid, "day": day, "kind": "compare", "count": 20,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            qid = _create_query(s, "TEST_rl compare should be blocked")
            r = s.post(f"{API}/queries/{qid}/compare",
                       headers={"X-User-Id": uid}, timeout=60)
            assert r.status_code == 429, f"expected 429, got {r.status_code}: {r.text}"
            body = r.json()
            detail = body.get("detail", "")
            assert "free" in detail.lower() or "limit" in detail.lower(), detail
            # Should reference limit=20
            assert "20" in detail
        finally:
            mongo["users"].delete_one({"id": uid})
            mongo["usage_events"].delete_many({"user_id": uid})


# ---------------- Providers/plans regression ----------------

class TestProvidersAndPlansRegression:
    def test_providers_five_slots(self, s):
        r = s.get(f"{API}/providers", timeout=30)
        assert r.status_code == 200
        provs = r.json()["providers"]
        assert len(provs) == 5

    def test_plans_free_available(self, s):
        r = s.get(f"{API}/plans", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["active_plan"] == "free"
        by_id = {p["id"]: p for p in data["plans"]}
        assert by_id["free"]["available"] is True
        assert by_id["premium"]["available"] is False
        assert by_id["byok"]["available"] is False


# ---------------- Smart Reuse threshold unchanged ----------------

class TestSmartReuseThreshold:
    def test_jaccard_fallback_055(self, s):
        r = s.post(f"{API}/queries/match", json={"prompt": "how do python asyncio queues work"}, timeout=30)
        assert r.status_code == 200
        thr = r.json()["thresholds"]
        assert thr["jaccard_fallback"] == 0.55


# ---------------- Encryption invariant ----------------

class TestEncryptionRefusal:
    def test_user_keys_refuses_without_env(self):
        # Ensure module reads env at call time; make sure it's unset for this test
        os.environ.pop("USER_KEY_ENCRYPTION_KEY", None)
        import importlib
        mod = importlib.import_module("services.user_keys")
        importlib.reload(mod)
        # Try to store — should refuse (return False) since key is unset
        import asyncio

        async def _run():
            return await mod.set_user_key(user_id="TEST_enc_refuse", provider_id="model-a", api_key="sk-fake")

        result = asyncio.get_event_loop().run_until_complete(_run()) if False else asyncio.run(_run())
        assert result is False
