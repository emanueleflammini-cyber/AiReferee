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
                "model_agreement": "low",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "what_could_change_the_verdict": [],
    }
    payload.update(overrides)
    return payload


def response(provider_id, status, text):
    labels = {
        "model-a": "ChatGPT",
        "model-c": "Gemini",
        "model-e": "Mistral",
    }
    providers = {
        "model-a": "OpenAI",
        "model-c": "Google DeepMind",
        "model-e": "Mistral AI",
    }
    return {
        "id": provider_id,
        "label": labels[provider_id],
        "provider_name": providers[provider_id],
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


def test_live_mistral_evidence_uses_stable_provider_key():
    answers = eligible_synthesis_answers(
        [
            {
                "id": "model-e",
                "label": "Mistral",
                "provider_name": "Mistral AI",
                "provider_status": "LIVE",
                "text": "Mistral evidence",
            }
        ],
        "LIVE",
    )
    assert len(answers) == 1
    assert answers[0]["provider_key"] == "mistral"
    assert answers[0]["text"] == "Mistral evidence"


def test_three_live_providers_are_all_eligible_for_one_conclusion():
    answers = eligible_synthesis_answers(
        [
            response("model-a", "LIVE", "OpenAI evidence"),
            response("model-c", "LIVE", "Gemini evidence"),
            response("model-e", "LIVE", "Mistral evidence"),
        ],
        "LIVE",
    )
    assert [item["provider_key"] for item in answers] == [
        "openai",
        "gemini",
        "mistral",
    ]

    conclusion = parse_structured_conclusion(
        valid_conclusion(
            agreements=[
                {
                    "id": "agreement_all",
                    "claim": "All usable providers support the core claim.",
                    "supporting_models": ["openai", "gemini", "mistral"],
                    "strength": "strong",
                    "reason": "The claim appears in all three responses.",
                }
            ],
            confidence={
                "level": "high",
                "reason": "All usable providers support the core claim.",
                "factors": {
                    "model_agreement": "high",
                    "evidence_quality": "medium",
                    "uncertainty": "low",
                },
            },
        ),
        ["openai", "gemini", "mistral"],
    )
    assert conclusion.agreements[0].supporting_models == [
        "openai",
        "gemini",
        "mistral",
    ]


def test_structured_conclusion_accepts_mistral_as_panel_evidence():
    payload = valid_conclusion(
        strongest_evidence=[
            {
                "id": "e_mistral",
                "claim": "Mistral supplied relevant evidence.",
                "description": "The claim appears in the Mistral response.",
                "supporting_models": ["mistral"],
                "source_status": "model_reasoning",
            }
        ],
    )
    conclusion = parse_structured_conclusion(
        payload,
        allowed_providers=["openai", "gemini", "mistral"],
    )
    assert conclusion.strongest_evidence[0].supporting_models == ["mistral"]


def test_structured_disagreement_accepts_mistral_position():
    conclusion = parse_structured_conclusion(
        valid_conclusion(
            disagreements=[
                {
                    "id": "mistral_disagreement",
                    "topic": "Current request limit",
                    "positions": [
                        {
                            "model": "openai",
                            "position": "The limit is ten.",
                        },
                        {
                            "model": "mistral",
                            "position": "The limit is twenty.",
                        },
                    ],
                    "referee_assessment": "The supplied responses conflict.",
                    "missing_information": "A current authoritative limit.",
                }
            ]
        ),
        ["openai", "mistral"],
    )
    assert {
        position.model for position in conclusion.disagreements[0].positions
    } == {"openai", "mistral"}


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


def test_failed_mistral_is_excluded_from_remaining_two_provider_synthesis():
    answers = eligible_synthesis_answers(
        [
            response("model-a", "LIVE", "OpenAI evidence"),
            response("model-c", "LIVE", "Gemini evidence"),
            response("model-e", "FAILED", ""),
        ],
        "LIVE",
    )
    assert [answer["provider_key"] for answer in answers] == [
        "openai",
        "gemini",
    ]
    with pytest.raises(ValueError, match="outside the current execution"):
        parse_structured_conclusion(
            valid_conclusion(
                strongest_evidence=[
                    {
                        "id": "invalid_mistral",
                        "claim": "Failed provider evidence.",
                        "description": "This must not enter the conclusion.",
                        "supporting_models": ["mistral"],
                        "source_status": "model_reasoning",
                    }
                ]
            ),
            ["openai", "gemini"],
        )


def test_single_provider_requires_explicitly_limited_model_agreement():
    parsed = parse_structured_conclusion(
        valid_conclusion(),
        ["mistral"],
    )
    assert parsed.agreements == []
    assert parsed.confidence.factors.model_agreement == "low"

    invalid = valid_conclusion()
    invalid["confidence"]["factors"]["model_agreement"] = "medium"
    with pytest.raises(ValueError, match="single-provider"):
        parse_structured_conclusion(invalid, ["mistral"])


def test_both_failed_produce_no_synthesis_evidence():
    answers = eligible_synthesis_answers(
        [
            response("model-a", "FAILED", ""),
            response("model-c", "FAILED", ""),
        ],
        "LIVE",
    )
    assert answers == []


def test_synthesizer_rejects_no_provider_evidence_without_api_call():
    synth, completions = synthesizer_with_outputs([])
    with pytest.raises(SynthesisFailure, match="no provider"):
        asyncio.run(
            synth.synthesize(
                "Question",
                [
                    response("model-a", "FAILED", ""),
                    response("model-c", "TIMEOUT", ""),
                    response("model-e", "FAILED", ""),
                ],
                "en",
            )
        )
    assert completions.calls == 0


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
                    {
                        "model": "openai",
                        "position": "Option A",
                        "evidence_claim_ids": ["claim_openai"],
                    },
                    {
                        "model": "gemini",
                        "position": "Option B",
                        "evidence_claim_ids": ["claim_gemini"],
                    },
                ],
                "referee_assessment": "The question does not resolve the trade-off.",
                "missing_information": "A current independent comparison.",
            }
        ],
        referee_reasoning="The shared evidence supports the core answer.",
    )
    parsed = parse_structured_conclusion(conclusion, ["openai", "gemini"])
    assert parsed.agreements[0].strength == "strong"
    assert len(parsed.disagreements[0].positions) == 2
    assert parsed.disagreements[0].missing_information.startswith("A current")
    assert parsed.disagreements[0].positions[0].evidence_claim_ids == ["claim_openai"]
    assert parsed.referee_reasoning.startswith("The shared evidence")


def test_empty_optional_sections_are_valid():
    parsed = parse_structured_conclusion(valid_conclusion(), ["openai"])
    assert parsed.agreements == []
    assert parsed.unsupported_claims == []
    assert parsed.referee_reasoning == ""


def test_pre_phase5_saved_conclusion_remains_compatible():
    old_payload = valid_conclusion(
        disagreements=[
            {
                "id": "d1",
                "topic": "Old saved disagreement",
                "positions": [
                    {"model": "openai", "position": "Option A"},
                    {"model": "gemini", "position": "Option B"},
                ],
                "referee_assessment": "Old records did not contain Phase 5 fields.",
            }
        ],
    )
    normalized, schema_version = normalize_stored_conclusion(
        {"trusted_conclusion_structured": old_payload}
    )
    assert schema_version == "2.0"
    assert normalized["referee_reasoning"] == ""
    assert normalized["disagreements"][0]["missing_information"] == ""
    assert normalized["disagreements"][0]["positions"][0]["evidence_claim_ids"] == []


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
