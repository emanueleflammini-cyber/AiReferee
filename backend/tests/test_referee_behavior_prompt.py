"""Referee 3.0 Phase A behavioral prompt contract tests."""
from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import (  # noqa: E402
    eligible_synthesis_answers,
)
from providers.synthesizer import (  # noqa: E402
    SynthesisBundleV3,
    _system_prompt,
)


def behavior_prompt(
    provider_labels: dict[str, str] | None = None,
) -> str:
    labels = provider_labels or {
        "openai": "ChatGPT",
        "gemini": "Gemini",
        "mistral": "Mistral",
    }
    return _system_prompt(
        target_name="English",
        audience="professional",
        fmt="paragraph",
        allowed_providers=list(labels),
        provider_labels=labels,
        execution_mode="LIVE",
    )


def test_three_provider_agreement_requires_names_and_shared_proposition():
    prompt = behavior_prompt()

    assert (
        "The only participating provider labels in this execution are: "
        "ChatGPT, Gemini, and Mistral."
    ) in prompt
    assert "specific proposition they share" in prompt
    assert "ChatGPT, Gemini, and Mistral agree that ..." in prompt
    assert "Never use only a generic statement" in prompt


def test_real_disagreement_requires_positions_and_verdict_impact():
    prompt = behavior_prompt()

    assert "genuinely incompatible positions" in prompt
    assert "each provider's specific position" in prompt
    assert "low, medium, or high impact on the final verdict" in prompt
    assert "missing_information that could resolve it" in prompt


def test_exclusive_detail_is_not_automatic_truth_or_disagreement():
    prompt = behavior_prompt()

    assert "exclusive contribution" in prompt
    assert "not automatically as truth or disagreement" in prompt
    assert "assess whether the supplied response evidence supports it" in prompt


def test_omission_and_different_emphasis_are_not_contradictions():
    prompt = behavior_prompt()

    assert (
        "Different emphasis, different caution, extra non-contradicted "
        "information, and omission are not disagreements."
    ) in prompt
    assert "no substantial contradiction emerged" in prompt


def test_failed_provider_is_excluded_from_participants():
    responses = [
        {
            "id": "model-a",
            "provider_response_id": "openai",
            "provider_key": "openai",
            "label": "ChatGPT",
            "provider": "OpenAI",
            "provider_status": "LIVE",
            "text": "OpenAI evidence.",
        },
        {
            "id": "model-c",
            "provider_response_id": "gemini",
            "provider_key": "gemini",
            "label": "Gemini",
            "provider": "Google DeepMind",
            "provider_status": "FAILED",
            "text": "",
        },
        {
            "id": "model-e",
            "provider_response_id": "mistral",
            "provider_key": "mistral",
            "label": "Mistral",
            "provider": "Mistral AI",
            "provider_status": "LIVE",
            "text": "Mistral evidence.",
        },
    ]
    eligible = eligible_synthesis_answers(responses, "LIVE")
    labels = {
        answer["provider_key"]: answer["label"]
        for answer in eligible
    }
    prompt = behavior_prompt(labels)

    assert list(labels) == ["openai", "mistral"]
    assert (
        "The only participating provider labels in this execution are: "
        "ChatGPT and Mistral."
    ) in prompt
    assert "Gemini" not in prompt
    assert "FAILED providers are absent" in prompt


def test_missing_sources_must_be_disclosed_without_invention():
    prompt = behavior_prompt()

    assert "Do not create URLs, citation IDs, source titles" in prompt
    assert "contain no usable source references" in prompt
    assert "verifiable sources are missing" in prompt
    assert "Every conclusion statement must be attributable" in prompt


def test_behavior_changes_preserve_existing_bundle_schema():
    bundle = SynthesisBundleV3.model_validate(
        {
            "trusted_conclusion": {
                "schema_version": "2.0",
                "final_answer": (
                    "ChatGPT and Mistral provide the available evidence."
                ),
                "agreements": [],
                "disagreements": [],
                "strongest_evidence": [],
                "remaining_uncertainties": [],
                "unsupported_claims": [],
                "confidence": {
                    "level": "low",
                    "reason": "No verifiable source references were supplied.",
                    "factors": {
                        "model_agreement": "low",
                        "evidence_quality": "low",
                        "uncertainty": "high",
                    },
                },
                "referee_reasoning": (
                    "No substantial contradiction emerged, but evidence "
                    "quality remains limited."
                ),
                "what_could_change_the_verdict": [],
            },
            "claim_analysis": {
                "schema_version": "3.0",
                "execution_mode": "LIVE",
                "claims": [],
            },
        }
    )
    schema = SynthesisBundleV3.model_json_schema()

    assert bundle.trusted_conclusion.schema_version == "2.0"
    assert bundle.claim_analysis.schema_version == "3.0"
    assert set(schema["properties"]) == {
        "trusted_conclusion",
        "claim_analysis",
    }
    assert "exclusive_contributions" not in str(schema)
