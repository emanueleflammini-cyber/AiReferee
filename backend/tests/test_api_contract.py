"""Local API contract checks that never call paid provider endpoints."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server  # noqa: E402


client = TestClient(server.app)


def test_provider_catalog_exposes_active_mistral_and_future_slots(monkeypatch):
    monkeypatch.setenv("ENABLE_OPENAI", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ENABLE_GEMINI", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("ENABLE_MISTRAL", "true")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("ENABLE_GROK", "false")
    monkeypatch.setenv("ENABLE_CLAUDE", "false")

    response = client.get("/api/providers")

    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()["providers"]}
    assert providers["model-a"]["status"] == "live"
    assert providers["model-c"]["status"] == "live"
    assert providers["model-e"]["status"] == "live"
    assert providers["model-d"]["status"] == "coming_soon"
    assert providers["model-b"]["status"] == "premium_coming_soon"


def test_free_plan_contract_includes_all_three_integrated_providers():
    response = client.get("/api/plans")

    assert response.status_code == 200
    plans = {item["id"]: item for item in response.json()["plans"]}
    assert set(plans["free"]["allowed_provider_ids"]) == {
        "model-a",
        "model-c",
        "model-e",
    }
