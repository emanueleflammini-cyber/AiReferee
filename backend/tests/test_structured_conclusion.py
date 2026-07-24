"""Phase 2 tests for the validated Trusted Conclusion 2.0 contract."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import (  # noqa: E402
    eligible_synthesis_answers,
    normalize_stored_conclusion,
    parse_structured_conclusion,
)
from providers.synthesizer import SynthesisFailure, Synthesizer  # noqa: E402


def valid_conclusion(**overrides):
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
            "factors": {
                "model_agreement": "medium",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "what_could_change_the_verdict": [],
    }
    payload.update(overrides)
    return payload


def response(provider_id, status, text):
    return {
        "id": provider_id,
        "label": "ChatGPT" if provider_id == "model-a" else "Gemini",
        "provider_name": "OpenAI" if provider_id == "model-a" else "Google",
        "provider_status": status,
        "text": text,
    }


def test_live_conclusion_uses_only_live_evidence():
    answers = eligible_synthesis_answers(
        [
            response("model-a", "LIVE", "OpenAI answer"),
            response("model-c", "LIVE", "Gemini answer"),
            response("model-c", "MOCK", "Demo answer"),
        ],
        "LIVE",
    )
    assert [answer["provider_key"] for answer in answers] == ["openai", "gemini"]
    assert all(answer["provider_status"] == "LIVE" for answer in answers)


def test_demo_conclusion_is_separate_from_live_evidence():
    answers = eligible_synthesis_answers(
        [
            response("model-a", "LIVE", "Real answer"),
            response("model-a", "MOCK", "Demo answer"),
        ],
        "DEMO",
    )
    assert len(answers) == 1
    assert answers[0]["text"] == "Demo answer"
    assert answers[0]["provider_status"] == "MOCK"


def test_one_live_and_one_failed_keeps_only_successful_provider():
    answers = eligible_synthesis_answers(
        [
            response("model-a", "LIVE", "Usable answer"),
            response("model-c", "FAILED", ""),
        ],
        "LIVE",
    )
    assert [answer["provider_key"] for answer in answers] == ["openai"]


def test_both_failed_produce_no_synthesis_evidence():
    answers = eligible_synthesis_answers(
        [
            response("model-a", "FAILED", ""),
            response("model-c", "FAILED", ""),
        ],
        "LIVE",
    )
    assert answers == []


def test_structured_agreement_and_disagreement_are_validated():
    conclusion = valid_conclusion(
        agreements=[
            {
                "id": "a1",
                "claim": "Both providers agree.",
                "supporting_models": ["openai", "gemini"],
                "strength": "strong",
                "reason": "The same claim appears in both responses.",
            }
        ],
        disagreements=[
            {
                "id": "d1",
                "topic": "Implementation detail",
                "positions": [
                    {"model": "openai", "position": "Option A"},
                    {"model": "gemini", "position": "Option B"},
                ],
                "referee_assessment": "The question does not resolve the trade-off.",
            }
        ],
    )
    parsed = parse_structured_conclusion(conclusion, ["openai", "gemini"])
    assert parsed.agreements[0].strength == "strong"
    assert len(parsed.disagreements[0].positions) == 2


def test_empty_optional_sections_are_valid():
    parsed = parse_structured_conclusion(valid_conclusion(), ["openai"])
    assert parsed.agreements == []
    assert parsed.unsupported_claims == []


def test_unknown_provider_reference_is_rejected():
    conclusion = valid_conclusion(
        agreements=[
            {
                "id": "a1",
                "claim": "Claim",
                "supporting_models": ["openai", "claude"],
                "strength": "weak",
                "reason": "Reason",
            }
        ]
    )
    with pytest.raises(ValueError):
        parse_structured_conclusion(conclusion, ["openai", "gemini"])


def test_urls_and_numeric_confidence_are_rejected():
    with pytest.raises(ValueError, match="must not contain source URLs"):
        parse_structured_conclusion(
            valid_conclusion(final_answer="See https://example.com"),
            ["openai"],
        )
    with pytest.raises(ValueError, match="qualitative"):
        parse_structured_conclusion(
            valid_conclusion(
                confidence={
                    "level": "high",
                    "reason": "Confidence is 92%.",
                    "factors": {
                        "model_agreement": "high",
                        "evidence_quality": "high",
                        "uncertainty": "low",
                    },
                }
            ),
            ["openai"],
        )


def test_legacy_record_is_preserved_without_fabricating_structure():
    structured, schema_version = normalize_stored_conclusion(
        {"trusted_conclusion": "Old free-text conclusion"}
    )
    assert structured is None
    assert schema_version == "legacy"


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


def synthesizer_with_outputs(outputs):
    synth = Synthesizer.__new__(Synthesizer)
    completions = FakeCompletions(outputs)
    synth.available = True
    synth._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return synth, completions


def test_invalid_json_gets_one_successful_repair():
    synth, completions = synthesizer_with_outputs(
        ["not json", json.dumps(valid_conclusion())]
    )
    result = asyncio.run(
        synth.synthesize(
            "Question",
            [
                {
                    "id": "model-a",
                    "provider_key": "openai",
                    "label": "ChatGPT",
                    "provider": "OpenAI",
                    "provider_status": "LIVE",
                    "text": "Answer",
                }
            ],
            "en",
        )
    )
    assert result["schema_version"] == "2.0"
    assert result["repair_attempted"] is True
    assert completions.calls == 2


def test_invalid_json_after_repair_fails_explicitly():
    synth, completions = synthesizer_with_outputs(["not json", "still not json"])
    with pytest.raises(SynthesisFailure, match="after one repair attempt"):
        asyncio.run(
            synth.synthesize(
                "Question",
                [
                    {
                        "id": "model-a",
                        "provider_key": "openai",
                        "label": "ChatGPT",
                        "provider": "OpenAI",
                        "provider_status": "LIVE",
                        "text": "Answer",
                    }
                ],
                "en",
            )
        )
    assert completions.calls == 2
