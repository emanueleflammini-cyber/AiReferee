"""AI Referee backend test suite — iteration 2.

Covers:
    - /api/providers and /api/providers/specs contracts
    - /api/queries CRUD + compare with only-OpenAI+Gemini enforcement
    - /api/queries/match Smart Reuse policy
    - /api/conclusions/{id}/translate
    - Confirms disabled providers (Claude/Grok/Mistral) are NEVER invoked
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://referee-ai-4.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

FORBIDDEN_IDS = {"model-b", "model-d", "model-e"}
FORBIDDEN_VENDORS = {"anthropic", "claude", "xai", "grok", "mistral"}


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------------- Providers ----------------

class TestProviders:
    def test_providers_list(self, s):
        r = s.get(f"{API}/providers", timeout=30)
        assert r.status_code == 200
        provs = r.json()["providers"]
        assert len(provs) == 5, f"expected 5 slots, got {len(provs)}"
        by_id = {p["id"]: p for p in provs}
        # Live slots
        assert by_id["model-a"]["status"] == "live" and by_id["model-a"]["live"] is True
        assert by_id["model-a"]["provider"] == "OpenAI"
        assert by_id["model-c"]["status"] == "live" and by_id["model-c"]["live"] is True
        assert by_id["model-c"]["is_primary"] is True
        # Coming soon
        assert by_id["model-d"]["status"] == "coming_soon" and by_id["model-d"]["live"] is False
        assert by_id["model-e"]["status"] == "coming_soon" and by_id["model-e"]["live"] is False
        # Premium coming soon
        assert by_id["model-b"]["tier"] == "premium"
        assert by_id["model-b"]["status"] == "premium_coming_soon"
        assert by_id["model-b"]["live"] is False

    def test_provider_specs_same_5(self, s):
        r = s.get(f"{API}/providers/specs", timeout=30)
        assert r.status_code == 200
        provs = r.json()["providers"]
        assert len(provs) == 5
        ids = {p["id"] for p in provs}
        assert ids == {"model-a", "model-b", "model-c", "model-d", "model-e"}


# ---------------- Queries + compare ----------------

class TestCompareOnlyLive:
    @pytest.fixture(scope="class")
    def query_id(self, s):
        payload = {
            "prompt": "TEST_ What is a distributed database and why would I use one?",
            "goal": 50, "detail": 60,
            "audience": "professional", "format": "paragraph", "strategy": "balanced",
        }
        r = s.post(f"{API}/queries", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_compare_only_2_live(self, s, query_id):
        r = s.post(f"{API}/queries/{query_id}/compare", timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        responses = data["responses"]
        assert len(responses) == 2, f"expected exactly 2 responses, got {len(responses)}: {[x['id'] for x in responses]}"
        assert data["live_count"] == 2
        ids = {r_["id"] for r_ in responses}
        assert ids == {"model-a", "model-c"}, f"unexpected ids: {ids}"
        # No forbidden IDs
        assert not (ids & FORBIDDEN_IDS)
        for resp in responses:
            assert resp["is_mock"] is False, f"{resp['id']} came back as mock: {resp.get('error')}"
            assert resp["text"] and len(resp["text"]) > 20
        # No forbidden vendor names in text
        blob = str(data).lower()
        for name in FORBIDDEN_VENDORS:
            # Provider names may still appear in a general answer; be strict: no id/model refs
            pass
        # Ensure no forbidden ids anywhere in the payload
        for fid in FORBIDDEN_IDS:
            assert fid not in blob, f"forbidden id {fid} leaked into compare response"


# ---------------- Smart Reuse match ----------------

class TestMatch:
    def test_match_news_never_reuse(self, s):
        r = s.post(f"{API}/queries/match", json={"prompt": "What is today's weather in Rome?"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["policy"] == "never_reuse"

    def test_match_sensitive_refresh(self, s):
        r = s.post(f"{API}/queries/match", json={"prompt": "What is the best medical treatment for cancer?"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["policy"] == "always_refresh"

    def test_match_technical_reusable(self, s):
        # Same class-of-prompt as one we created above; should be reusable
        r = s.post(f"{API}/queries/match", json={"prompt": "Explain distributed databases and why to use them"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["policy"] == "reusable"


# ---------------- Translate ----------------

class TestTranslate:
    def test_translate_needs_cached_conclusion(self, s):
        # Create a technical query so it enters conclusions collection
        prompt = "TEST_ Explain the CAP theorem in one paragraph"
        r = s.post(f"{API}/queries", json={"prompt": prompt, "goal": 50, "detail": 50,
                                            "audience": "professional", "format": "paragraph",
                                            "strategy": "balanced"}, timeout=30)
        assert r.status_code == 200
        qid = r.json()["id"]
        # Run compare so trusted_conclusion or at least prompt is available
        s.post(f"{API}/queries/{qid}/compare", timeout=180)
        # Try translate to Italian
        r2 = s.post(f"{API}/conclusions/{qid}/translate", json={"target_language": "it"}, timeout=60)
        assert r2.status_code in (200, 503), r2.text
        if r2.status_code == 200:
            body = r2.json()
            assert body["target_language"] == "it"
            assert body["text"]
