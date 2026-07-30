"""Referee 3.0 Phase B structured agreement-matrix tests."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import (  # noqa: E402
    eligible_synthesis_answers,
    normalize_stored_conclusion,
    parse_structured_conclusion,
)
from providers.synthesizer import (  # noqa: E402
    Synthesizer,
    _enrich_conclusion,
    _validate_conclusion_claim_references,
)
from providers.traceability_schema import ClaimAnalysisV3  # noqa: E402


PROVIDERS = ["openai", "gemini", "mistral"]


def load_fixture(name: str) -> dict:
    return json.loads(
        (FIXTURE_DIR / f"referee3_{name}.json").read_text(encoding="utf-8")
    )


def old_conclusion(**overrides) -> dict:
    payload = {
        "schema_version": "2.0",
        "final_answer": "A backward-compatible conclusion.",
        "agreements": [],
        "disagreements": [],
        "strongest_evidence": [],
        "remaining_uncertainties": [],
        "unsupported_claims": [],
        "confidence": {
            "level": "medium",
            "reason": "The supplied evidence is useful but limited.",
            "factors": {
                "model_agreement": "low",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "referee_reasoning": "",
        "what_could_change_the_verdict": [],
    }
    payload.update(overrides)
    return payload


def response(provider: str, status: str, text: str) -> dict:
    labels = {
        "openai": "ChatGPT",
        "gemini": "Gemini",
        "mistral": "Mistral",
    }
    return {
        "id": provider,
        "provider_key": provider,
        "provider_response_id": f"{provider}-response",
        "label": labels[provider],
        "provider": labels[provider],
        "provider_status": status,
        "text": text,
    }


def test_three_providers_can_be_unanimous():
    parsed = parse_structured_conclusion(load_fixture("unanimous"), PROVIDERS)
    assert parsed.claim_matrix[0].agreement_level == "unanimous"
    assert parsed.claim_agreements[0].providers == PROVIDERS


def test_two_supporters_and_one_contradiction_are_disputed():
    parsed = parse_structured_conclusion(load_fixture("disagreement"), PROVIDERS)
    item = parsed.claim_matrix[0]
    assert item.agreement_level == "disputed"
    assert {position.position for position in item.provider_positions} >= {
        "supports",
        "contradicts",
    }


def test_partial_support_is_distinct_from_full_support():
    payload = load_fixture("emphasis")
    payload["claim_matrix"][0]["provider_positions"][1]["position"] = (
        "partially_supports"
    )
    payload["claim_matrix"][0]["agreement_level"] = "partial_consensus"
    payload["claim_agreements"] = []
    parsed = parse_structured_conclusion(payload, PROVIDERS)
    assert parsed.claim_matrix[0].provider_positions[1].position == (
        "partially_supports"
    )


def test_uncertain_provider_position_is_preserved():
    parsed = parse_structured_conclusion(load_fixture("disagreement"), PROVIDERS)
    positions = {
        position.provider: position.position
        for position in parsed.claim_matrix[0].provider_positions
    }
    assert positions["mistral"] == "uncertain"


def test_not_mentioned_is_not_treated_as_contradiction():
    parsed = parse_structured_conclusion(load_fixture("emphasis"), PROVIDERS)
    positions = {
        position.provider: position.position
        for position in parsed.claim_matrix[0].provider_positions
    }
    assert positions["mistral"] == "not_mentioned"
    assert parsed.claim_disagreements == []


def test_exclusive_detail_is_not_classified_as_disagreement():
    parsed = parse_structured_conclusion(load_fixture("emphasis"), PROVIDERS)
    assert parsed.exclusive_contributions[0].provider == "gemini"
    assert parsed.claim_disagreements == []


def test_degree_disagreement_is_valid():
    parsed = parse_structured_conclusion(load_fixture("disagreement"), PROVIDERS)
    assert parsed.claim_disagreements[0].disagreement_type == "degree"
    assert parsed.claim_disagreements[0].impact_on_verdict == "high"


def test_timeframe_disagreement_is_valid():
    payload = load_fixture("disagreement")
    payload["claim_disagreements"][0]["disagreement_type"] = "timeframe"
    parsed = parse_structured_conclusion(payload, PROVIDERS)
    assert parsed.claim_disagreements[0].disagreement_type == "timeframe"


def test_emphasis_without_incompatible_positions_has_no_disagreement():
    parsed = parse_structured_conclusion(load_fixture("emphasis"), PROVIDERS)
    assert parsed.claim_disagreements == []
    assert parsed.claim_matrix[0].agreement_level == "strong_consensus"


def test_failed_provider_is_excluded_from_live_matrix_input():
    answers = eligible_synthesis_answers(
        [
            response("openai", "LIVE", "OpenAI evidence"),
            response("gemini", "LIVE", "Gemini evidence"),
            response("mistral", "FAILED", ""),
        ],
        "LIVE",
    )
    assert [answer["provider_key"] for answer in answers] == [
        "openai",
        "gemini",
    ]


def test_mock_provider_is_excluded_from_live_matrix_input():
    answers = eligible_synthesis_answers(
        [
            response("openai", "LIVE", "OpenAI evidence"),
            response("gemini", "MOCK", "Mock evidence"),
        ],
        "LIVE",
    )
    assert [answer["provider_key"] for answer in answers] == ["openai"]


def test_duplicate_claim_ids_are_rejected():
    payload = load_fixture("unanimous")
    payload["claim_matrix"].append(dict(payload["claim_matrix"][0]))
    with pytest.raises(ValueError, match="claim matrix IDs must be unique"):
        parse_structured_conclusion(payload, PROVIDERS)


def test_unknown_claim_id_in_agreement_is_rejected():
    payload = load_fixture("unanimous")
    payload["claim_agreements"][0]["claim_ids"] = ["claim_missing"]
    with pytest.raises(ValueError, match="unknown claim IDs"):
        parse_structured_conclusion(payload, PROVIDERS)


def test_disagreement_incompatible_with_positions_is_rejected():
    payload = load_fixture("unanimous")
    payload["claim_agreements"] = []
    payload["claim_disagreements"] = [
        {
            "topic": "Artificial conflict",
            "claim_ids": ["claim_automation"],
            "positions": [
                {"provider": "openai", "position": "Position A"},
                {"provider": "gemini", "position": "Position B"},
            ],
            "disagreement_type": "interpretation",
            "impact_on_verdict": "low",
            "referee_resolution": "This must be rejected.",
        }
    ]
    with pytest.raises(
        ValueError,
        match="incompatible with provider positions",
    ):
        parse_structured_conclusion(payload, PROVIDERS)


def test_unanimous_rejects_a_contradicting_provider():
    payload = load_fixture("unanimous")
    payload["claim_matrix"][0]["provider_positions"][2]["position"] = (
        "contradicts"
    )
    with pytest.raises(ValueError, match="unanimous"):
        parse_structured_conclusion(payload, PROVIDERS)


def test_old_saved_conclusion_defaults_new_sections_to_empty():
    parsed = parse_structured_conclusion(old_conclusion(), ["openai"])
    assert parsed.claim_matrix == []
    assert parsed.claim_agreements == []
    assert parsed.claim_disagreements == []
    assert parsed.exclusive_contributions == []
    assert parsed.decisive_factors == []


def test_deterministic_fallback_builds_minimum_supported_matrix():
    conclusion = parse_structured_conclusion(
        old_conclusion(),
        ["openai", "gemini"],
    )
    analysis = ClaimAnalysisV3.model_validate(
        {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [
                {
                    "id": "claim_shared",
                    "text": "Both responses explicitly support this claim.",
                    "claim_type": "fact",
                    "originating_models": ["openai", "gemini"],
                    "supporting_models": ["openai", "gemini"],
                    "disputing_models": [],
                    "support": [
                        {
                            "provider": "openai",
                            "response_excerpt": "Both responses support the claim.",
                            "response_reference": {
                                "provider_response_id": "openai-response"
                            },
                        },
                        {
                            "provider": "gemini",
                            "response_excerpt": "Both responses support the claim.",
                            "response_reference": {
                                "provider_response_id": "gemini-response"
                            },
                        },
                    ],
                    "dispute": [],
                    "citation_ids": [],
                    "assessment": {
                        "status": "supported",
                        "reason": "Two exact excerpts support the claim.",
                    },
                }
            ],
        }
    )
    enriched = _enrich_conclusion(
        conclusion,
        analysis,
        [],
        [
            response("openai", "LIVE", "Both responses support the claim."),
            response("gemini", "LIVE", "Both responses support the claim."),
        ],
    )
    assert enriched.claim_matrix[0].agreement_level == "unanimous"
    assert len(enriched.claim_agreements) == 1


class FakeCompletions:
    def __init__(self, outputs: list[str]):
        self.outputs = iter(outputs)
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=next(self.outputs))
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            model="fixture-synthesizer",
        )


def test_json_repair_recovers_a_malformed_optional_matrix():
    invalid = old_conclusion(claim_matrix={"not": "a list"})
    repaired = old_conclusion()
    completions = FakeCompletions(
        [json.dumps(invalid), json.dumps(repaired)]
    )
    synth = Synthesizer.__new__(Synthesizer)
    synth.available = True
    synth._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    result = asyncio.run(
        synth.synthesize(
            "Question",
            [response("openai", "LIVE", "Answer")],
            "en",
        )
    )
    assert result["repair_attempted"] is True
    assert result["structured_conclusion"]["claim_matrix"] == []
    assert completions.calls == 2


def test_mongo_compatible_round_trip_preserves_new_fields():
    stored_document = json.loads(json.dumps(load_fixture("unanimous")))
    normalized, version = normalize_stored_conclusion(
        {"trusted_conclusion_structured": stored_document}
    )
    assert version == "2.0"
    assert normalized["claim_matrix"][0]["claim_id"] == "claim_automation"
    assert normalized["decisive_factors"][0]["weight"] == "high"


def test_provider_outside_live_panel_is_rejected():
    payload = load_fixture("unanimous")
    with pytest.raises(ValueError, match="outside the current execution"):
        parse_structured_conclusion(payload, ["openai", "gemini"])


def test_claim_matrix_requires_every_participating_provider():
    payload = load_fixture("unanimous")
    payload["claim_matrix"][0]["provider_positions"] = (
        payload["claim_matrix"][0]["provider_positions"][:2]
    )
    payload["claim_matrix"][0]["agreement_level"] = "unanimous"
    payload["claim_agreements"][0]["providers"] = ["openai", "gemini"]
    with pytest.raises(ValueError, match="every participating provider"):
        parse_structured_conclusion(payload, PROVIDERS)


def test_unknown_evidence_reference_is_rejected_against_execution_data():
    payload = load_fixture("emphasis")
    payload["claim_matrix"][0]["provider_positions"][0]["evidence_refs"] = [
        "invented-reference"
    ]
    conclusion = parse_structured_conclusion(payload, PROVIDERS)
    analysis = ClaimAnalysisV3.model_validate(
        {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [
                {
                    "id": "claim_assistance",
                    "text": "AI will increasingly assist programmers.",
                    "claim_type": "prediction",
                    "originating_models": ["openai", "gemini"],
                    "supporting_models": ["openai", "gemini"],
                    "disputing_models": [],
                    "support": [
                        {
                            "provider": "openai",
                            "response_excerpt": "AI assistance will expand.",
                            "response_reference": {
                                "provider_response_id": "openai-response"
                            },
                        },
                        {
                            "provider": "gemini",
                            "response_excerpt": "AI assistance will expand.",
                            "response_reference": {
                                "provider_response_id": "gemini-response"
                            },
                        },
                    ],
                    "dispute": [],
                    "citation_ids": [],
                    "assessment": {
                        "status": "supported",
                        "reason": "Two providers support the claim.",
                    },
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="unknown evidence IDs"):
        _validate_conclusion_claim_references(
            conclusion,
            analysis,
            [
                response("openai", "LIVE", "Evidence"),
                response("gemini", "LIVE", "Evidence"),
                response("mistral", "LIVE", "Evidence"),
            ],
            [],
        )


def test_stored_two_provider_matrix_remains_readable_without_migration():
    payload = load_fixture("emphasis")
    payload["claim_matrix"][0]["provider_positions"] = (
        payload["claim_matrix"][0]["provider_positions"][:2]
    )
    normalized, version = normalize_stored_conclusion(
        {"trusted_conclusion_structured": payload}
    )
    assert version == "2.0"
    assert normalized["claim_matrix"][0]["claim_id"] == "claim_assistance"
