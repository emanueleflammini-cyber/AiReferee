"""Backend tests for multilingual Trusted Conclusion pipeline (iteration_5)."""
import os
import re
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://referee-ai-4.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ITALIAN_HINTS = re.compile(r"[àèéìòù]|\b(il|la|un|una|di|che|per|con|sono|questo|questa|essere)\b", re.IGNORECASE)
FRENCH_HINTS = re.compile(r"[àâçéèêëîïôùûü]|\b(le|la|les|un|une|des|est|pour|avec|dans|cette)\b", re.IGNORECASE)
SPANISH_HINTS = re.compile(r"[áéíñóúü¿¡]|\b(el|la|los|las|un|una|es|para|con|este|esta)\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _unique(text):
    return f"{text} [{uuid.uuid4().hex[:8]}]"


# ---------- Regression: providers, plans, me ----------

def test_providers_5_slots(s):
    r = s.get(f"{API}/providers", timeout=30)
    assert r.status_code == 200
    data = r.json()
    slots = data.get("providers") or data
    assert len(slots) == 5


def test_plans_3(s):
    r = s.get(f"{API}/plans", timeout=30)
    assert r.status_code == 200
    plans = r.json()
    if isinstance(plans, dict):
        plans = plans.get("plans", plans)
    assert len(plans) == 3


def test_me_anonymous(s):
    r = s.get(f"{API}/me", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data.get("plan", "").upper() in ("FREE", "ANONYMOUS", "STARTER") or "plan" in data


# ---------- QueryCreate accepts answer_language ----------

def test_query_create_accepts_answer_language(s):
    prompt = _unique("Come funziona un motore elettrico sincrono")
    r = s.post(f"{API}/queries", json={"prompt": prompt, "answer_language": "it"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("answer_language") == "it"
    assert data.get("id")


def test_match_thresholds_070(s):
    r = s.post(f"{API}/queries/match", json={"prompt": _unique("What is quantum tunneling"), "answer_language": "en"}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    thr = data.get("thresholds") or {}
    assert thr.get("jaccard_fallback") == 0.70


def test_language_supported_pt(s):
    """SUPPORTED includes pt — verified indirectly via /queries/match with pt."""
    r = s.post(f"{API}/queries/match", json={"prompt": _unique("Como funciona uma bateria de litio"), "answer_language": "pt"}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data.get("thresholds", {}).get("jaccard_fallback") == 0.70


# ---------- Compare synthesises Trusted Conclusion in target language ----------

def _create_and_compare(s, prompt, lang, timeout=180):
    q = s.post(f"{API}/queries", json={"prompt": prompt, "answer_language": lang}, timeout=30)
    assert q.status_code == 200, q.text
    qid = q.json()["id"]
    r = s.post(f"{API}/queries/{qid}/compare", json={}, timeout=timeout)
    assert r.status_code == 200, r.text
    return qid, r.json()


def test_compare_italian_conclusion(s):
    qid, data = _create_and_compare(s, _unique("Spiegami come funziona la fotosintesi in modo semplice"), "it")
    assert data.get("answer_language") == "it"
    tc = data.get("trusted_conclusion") or ""
    assert len(tc) > 20, f"Empty conclusion: {data}"
    assert ITALIAN_HINTS.search(tc), f"Conclusion not Italian: {tc[:400]}"
    assert "synthesis_model" in data and data["synthesis_model"]
    assert "synthesis_latency_ms" in data
    assert "synthesis_cost_usd" in data
    # only OpenAI + Gemini panellists
    providers = {(r.get("provider") or "").lower() for r in data.get("responses", [])}
    # provider label may be "OpenAI" / "Google DeepMind" — assert only these two families
    assert len(providers) == 2
    assert any("openai" in p for p in providers)
    assert any("google" in p or "gemini" in p or "deepmind" in p for p in providers)
    assert len(data.get("responses", [])) == 2


def test_compare_english_conclusion(s):
    qid, data = _create_and_compare(s, _unique("Explain how a heat pump works in simple terms"), "en")
    assert data.get("answer_language") == "en"
    tc = data.get("trusted_conclusion") or ""
    assert len(tc) > 20
    # Should NOT be dominated by Italian accents
    assert not re.search(r"[àèìòù]", tc[:200])


def test_compare_french_conclusion(s):
    qid, data = _create_and_compare(s, _unique("Explique moi comment fonctionne la photosynthese des plantes"), "fr")
    tc = data.get("trusted_conclusion") or ""
    assert len(tc) > 20
    assert FRENCH_HINTS.search(tc), f"Not French: {tc[:300]}"


# ---------- On-demand translation via GET /api/conclusions/{id} ----------

def test_conclusion_get_translate_spanish_and_cache(s):
    qid, data = _create_and_compare(s, _unique("Explain how photovoltaic solar cells convert light into electricity"), "en")
    # 1st call: Spanish (not cached yet from compare, which cached English)
    r1 = s.get(f"{API}/conclusions/{qid}", params={"lang": "es"}, timeout=90)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1.get("language") == "es"
    assert len(d1.get("trusted_conclusion") or "") > 20
    assert SPANISH_HINTS.search(d1["trusted_conclusion"]), d1["trusted_conclusion"][:300]

    # 2nd call same lang: cache_hit true
    r2 = s.get(f"{API}/conclusions/{qid}", params={"lang": "es"}, timeout=30)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2.get("cache_hit") is True

    # 3rd call different lang: fr
    r3 = s.get(f"{API}/conclusions/{qid}", params={"lang": "fr"}, timeout=90)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3.get("language") == "fr"
    assert FRENCH_HINTS.search(d3.get("trusted_conclusion") or "")


# ---------- No self-match at 100% after create_query ----------

def test_create_query_does_not_seed_conclusions(s):
    prompt = _unique("Come si progetta un algoritmo di ordinamento efficiente per grandi dataset in Python")
    q = s.post(f"{API}/queries", json={"prompt": prompt, "answer_language": "it"}, timeout=30)
    assert q.status_code == 200
    # Immediately match with the exact same prompt — should NOT self-match 100%.
    r = s.post(f"{API}/queries/match", json={"prompt": prompt, "answer_language": "it"}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    match = data.get("match")
    # Either no match at all, or match with sim < 100 (from a different prior conclusion).
    if match:
        assert match.get("similarity", 0) < 100, f"Self-match detected: {match}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
