"""AI Referee backend test suite — iteration 3.

Covers:
    - Existing regressions:
        * /api/providers and /api/providers/specs contracts (5 slots)
        * /api/queries CRUD + three-provider compare enforcement
        * /api/queries/match Smart Reuse policy + jaccard_fallback threshold from env
        * /api/conclusions/{id}/translate
        * Confirms disabled providers (Claude/Grok) are NEVER invoked
    - NEW:
        * GET /api/plans catalog contract (free/premium/byok)
        * SMART_REUSE_THRESHOLD env value surfaced via /queries/match thresholds
        * Claude wiring activation smoke-test (ENABLE_CLAUDE + fake key)
        * BYOK abstraction: resolve_api_key precedence
        * user_keys.set_user_key refuses when USER_KEY_ENCRYPTION_KEY unset
        * requirements.txt exposes anthropic + cryptography importable
"""
import os
import sys
import time
import subprocess
from pathlib import Path
import pytest
import requests

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

FORBIDDEN_IDS = {"model-b", "model-d"}


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
        assert by_id["model-a"]["status"] == "live" and by_id["model-a"]["live"] is True
        assert by_id["model-c"]["status"] == "live" and by_id["model-c"]["is_primary"] is True
        assert by_id["model-d"]["status"] == "coming_soon"
        assert by_id["model-e"]["status"] == "live"
        assert by_id["model-e"]["live"] is True
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


# ---------------- Plans catalog ----------------

class TestPlans:
    def test_plans_contract(self, s):
        r = s.get(f"{API}/plans", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["active_plan"] == "free"
        by_id = {p["id"]: p for p in data["plans"]}
        assert set(by_id.keys()) == {"free", "premium", "byok"}
        assert by_id["free"]["available"] is True
        assert by_id["premium"]["available"] is False
        assert by_id["byok"]["available"] is False
        # Allowed provider ids
        assert set(by_id["free"]["allowed_provider_ids"]) == {
            "model-a", "model-c", "model-e"
        }
        assert set(by_id["premium"]["allowed_provider_ids"]) == {
            "model-a", "model-b", "model-c", "model-d", "model-e"
        }
        assert set(by_id["byok"]["allowed_provider_ids"]) == {
            "model-a", "model-b", "model-c", "model-d", "model-e"
        }
        assert by_id["byok"]["can_use_own_keys"] is True
        assert by_id["free"]["can_use_own_keys"] is False
        assert by_id["premium"]["can_use_own_keys"] is False


# ---------------- Compare all 3 live providers ----------------

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

    def test_compare_all_3_live(self, s, query_id):
        r = s.post(f"{API}/queries/{query_id}/compare", timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        responses = data["responses"]
        assert len(responses) == 3, [x['id'] for x in responses]
        assert data["live_count"] == 3
        ids = {r_["id"] for r_ in responses}
        assert ids == {"model-a", "model-c", "model-e"}
        assert not (ids & FORBIDDEN_IDS)
        for resp in responses:
            assert resp["is_mock"] is False, f"{resp['id']} mock: {resp.get('error')}"
            assert resp["text"] and len(resp["text"]) > 20
        blob = str(data).lower()
        for fid in FORBIDDEN_IDS:
            assert fid not in blob, f"forbidden id {fid} leaked"


# ---------------- Match + threshold ----------------

class TestMatch:
    def test_match_thresholds_from_env(self, s):
        r = s.post(f"{API}/queries/match", json={"prompt": "any prompt to inspect thresholds"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "thresholds" in data, data
        expected = float(os.environ.get("SMART_REUSE_THRESHOLD", "0.55"))
        assert float(data["thresholds"]["jaccard_fallback"]) == pytest.approx(expected)

    def test_match_news_never_reuse(self, s):
        r = s.post(f"{API}/queries/match", json={"prompt": "What is today's weather in Rome?"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["policy"] == "never_reuse"

    def test_match_sensitive_refresh(self, s):
        r = s.post(f"{API}/queries/match", json={"prompt": "What is the best medical treatment for cancer?"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["policy"] == "always_refresh"


# ---------------- Claude wiring smoke-test ----------------

class TestClaudeWiring:
    def test_claude_flip_reports_live(self):
        """Import registry with ENABLE_CLAUDE=true + fake key; expect model-b status='live'.

        Runs in a subprocess so env changes don't leak into other tests.
        """
        code = (
            "import os,sys;"
            "os.environ['ENABLE_CLAUDE']='true';"
            "os.environ['ANTHROPIC_API_KEY']='sk-ant-fake-KEY-for-wiring-test';"
            f"sys.path.insert(0,{str(BACKEND_DIR)!r});"
            "from providers.registry import all_provider_specs;"
            "specs={p['id']:p for p in all_provider_specs()};"
            "print('MB_STATUS:', specs['model-b']['status']);"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, out.stderr
        assert "MB_STATUS: live" in out.stdout, out.stdout

    def test_claude_default_disabled_reports_premium_coming_soon(self):
        code = (
            "import sys;"
            f"sys.path.insert(0,{str(BACKEND_DIR)!r});"
            "from providers.registry import all_provider_specs;"
            "specs={p['id']:p for p in all_provider_specs()};"
            "print('MB_STATUS:', specs['model-b']['status']);"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, out.stderr
        assert "MB_STATUS: premium_coming_soon" in out.stdout, out.stdout


# ---------------- BYOK abstraction ----------------

class TestBYOK:
    def test_resolve_platform_key_for_model_a(self):
        # Ensure the canonical backend is importable and its local .env is loaded.
        from dotenv import load_dotenv
        load_dotenv(BACKEND_DIR / ".env")
        from providers.key_source import resolve_api_key  # noqa
        res = resolve_api_key("model-a")
        assert res is not None, "expected platform key for model-a"
        assert res.source == "platform"
        assert res.provider_id == "model-a"

    def test_resolve_model_b_none_on_free(self):
        from providers.key_source import resolve_api_key  # noqa
        # Free plan: model-b not in allowed ids -> None
        res = resolve_api_key("model-b")
        assert res is None, f"expected None for model-b under free plan, got {res}"


# ---------------- Encryption safety ----------------

class TestUserKeysEncryptionRefusal:
    def test_set_user_key_refuses_without_encryption_key(self):
        # Ensure USER_KEY_ENCRYPTION_KEY unset
        prev = os.environ.pop("USER_KEY_ENCRYPTION_KEY", None)
        try:
            import asyncio
            from services.user_keys import set_user_key
            ok = asyncio.get_event_loop().run_until_complete(
                set_user_key("TEST_user", "model-a", "sk-fake")
            ) if False else asyncio.run(set_user_key("TEST_user", "model-a", "sk-fake"))
            assert ok is False, "set_user_key must refuse without encryption key"
        finally:
            if prev is not None:
                os.environ["USER_KEY_ENCRYPTION_KEY"] = prev

    def test_user_keys_file_never_logs_raw(self):
        with open(BACKEND_DIR / "services" / "user_keys.py", encoding="utf-8") as f:
            src = f.read()
        # Any log line referencing api_key must wrap it in _hint(...) or _redact(...)
        for line in src.splitlines():
            low = line.strip()
            if low.startswith("log.") and "api_key" in line:
                assert "_hint(api_key)" in line or "_redact(api_key)" in line, (
                    f"raw api_key possibly logged: {line}"
                )


# ---------------- Requirements & imports ----------------

class TestRequirements:
    def test_anthropic_and_cryptography_importable(self):
        import importlib
        m1 = importlib.import_module("anthropic")
        m2 = importlib.import_module("cryptography.fernet")
        assert hasattr(m1, "AsyncAnthropic")
        assert hasattr(m2, "Fernet")

    def test_requirements_pins(self):
        with open(BACKEND_DIR / "requirements.txt", encoding="utf-8") as f:
            reqs = f.read().lower()
        assert "anthropic" in reqs
        assert "cryptography" in reqs


# ---------------- Translate ----------------

class TestTranslate:
    def test_translate_smoke(self, s):
        prompt = "TEST_ Explain the CAP theorem in one paragraph"
        r = s.post(f"{API}/queries", json={"prompt": prompt, "goal": 50, "detail": 50,
                                            "audience": "professional", "format": "paragraph",
                                            "strategy": "balanced"}, timeout=30)
        assert r.status_code == 200
        qid = r.json()["id"]
        s.post(f"{API}/queries/{qid}/compare", timeout=180)
        r2 = s.post(f"{API}/conclusions/{qid}/translate", json={"target_language": "it"}, timeout=60)
        assert r2.status_code in (200, 503), r2.text
        if r2.status_code == 200:
            body = r2.json()
            assert body["target_language"] == "it"
            assert body["text"]
