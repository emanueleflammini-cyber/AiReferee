"""Prompt/schema alignment tests for the two disagreement structures and
the TraceableClaim cross-field invariants.

These reproduce, offline and without any real API call, the exact
contamination patterns observed in production: fields from
trusted_conclusion.claim_disagreements[] leaking into
trusted_conclusion.disagreements[] (and vice versa), and claim_analysis
claims marked "supported" without a real support excerpt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import (  # noqa: E402
    ClaimDisagreement,
    Disagreement,
)
from providers.synthesizer import SynthesisBundleV3, _system_prompt  # noqa: E402
from providers.traceability_schema import TraceableClaim  # noqa: E402


def behavior_prompt() -> str:
    return _system_prompt(
        target_name="English",
        audience="professional",
        fmt="paragraph",
        allowed_providers=["openai", "gemini"],
        provider_labels={"openai": "ChatGPT", "gemini": "Gemini"},
        execution_mode="LIVE",
    )


# --- trusted_conclusion.disagreements[] vs claim_disagreements[] ----------


def valid_disagreement_payload() -> dict:
    return {
        "id": "disagreement_1",
        "topic": "Current request limit",
        "positions": [
            {"model": "openai", "position": "Ten.", "evidence_claim_ids": []},
            {"model": "gemini", "position": "Twenty.", "evidence_claim_ids": []},
        ],
        "referee_assessment": "The supplied responses conflict.",
        "missing_information": "An authoritative current limit.",
        "disputing_claim_ids": [],
    }


def valid_claim_disagreement_payload() -> dict:
    return {
        "topic": "Current request limit",
        "claim_ids": ["claim_limit"],
        "positions": [
            {"provider": "openai", "position": "Ten."},
            {"provider": "gemini", "position": "Twenty."},
        ],
        "disagreement_type": "factual",
        "impact_on_verdict": "medium",
        "referee_resolution": "The panel disagrees on the exact limit.",
    }


def test_disagreement_contaminated_with_claim_disagreement_fields_is_rejected():
    payload = valid_disagreement_payload()
    payload["disagreement_type"] = "factual"
    payload["impact_on_verdict"] = "high"
    payload["referee_resolution"] = "Resolved."
    with pytest.raises(ValidationError):
        Disagreement.model_validate(payload)


def test_claim_disagreement_contaminated_with_disagreement_fields_is_rejected():
    payload = valid_claim_disagreement_payload()
    payload["referee_assessment"] = "Should not be here."
    with pytest.raises(ValidationError):
        ClaimDisagreement.model_validate(payload)


def test_claim_disagreement_position_contaminated_with_evidence_claim_ids_is_rejected():
    payload = valid_claim_disagreement_payload()
    payload["positions"][0]["evidence_claim_ids"] = ["claim_limit"]
    with pytest.raises(ValidationError):
        ClaimDisagreement.model_validate(payload)


def test_disagreement_position_contaminated_with_provider_field_is_rejected():
    payload = valid_disagreement_payload()
    payload["positions"][0]["provider"] = "openai"
    with pytest.raises(ValidationError):
        Disagreement.model_validate(payload)


def test_correct_disagreement_structure_is_valid():
    disagreement = Disagreement.model_validate(valid_disagreement_payload())
    assert disagreement.referee_assessment == "The supplied responses conflict."
    assert disagreement.positions[0].model == "openai"


def test_correct_claim_disagreement_structure_is_valid():
    claim_disagreement = ClaimDisagreement.model_validate(
        valid_claim_disagreement_payload()
    )
    assert claim_disagreement.disagreement_type == "factual"
    assert claim_disagreement.positions[0].provider == "openai"


# --- TraceableClaim.validate_relationships() invariants -------------------


def _claim_support(provider: str, excerpt: str = "Example excerpt.") -> dict:
    return {
        "provider": provider,
        "response_excerpt": excerpt,
        "response_reference": {"provider_response_id": provider},
    }


def base_claim(**overrides) -> dict:
    payload = {
        "id": "claim_1",
        "text": "Example claim.",
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai"],
        "disputing_models": [],
        "support": [_claim_support("openai")],
        "dispute": [],
        "citation_ids": [],
        "assessment": {"status": "supported", "reason": "OpenAI supports it."},
    }
    payload.update(overrides)
    return payload


def test_supported_claim_without_support_excerpt_is_rejected():
    payload = base_claim(support=[])
    with pytest.raises(ValidationError, match="supported claim requires"):
        TraceableClaim.model_validate(payload)


def test_supported_claim_with_real_excerpt_is_valid():
    claim = TraceableClaim.model_validate(base_claim())
    assert claim.assessment.status == "supported"
    assert claim.support[0].provider == "openai"


def test_support_excerpt_provider_absent_from_supporting_models_is_rejected():
    payload = base_claim(supporting_models=[], support=[_claim_support("openai")])
    with pytest.raises(ValidationError, match="support excerpts require"):
        TraceableClaim.model_validate(payload)


def test_provider_cannot_be_both_supporter_and_disputer():
    payload = base_claim(supporting_models=["openai"], disputing_models=["openai"])
    with pytest.raises(ValidationError, match="cannot both support and dispute"):
        TraceableClaim.model_validate(payload)


def test_disputed_claim_without_disputing_models_is_rejected():
    payload = base_claim(
        supporting_models=[],
        support=[],
        disputing_models=[],
        assessment={"status": "disputed", "reason": "Gemini disagrees."},
    )
    with pytest.raises(ValidationError, match="disputed claim requires"):
        TraceableClaim.model_validate(payload)


# --- System prompt: path-specific instructions replace the ambiguous one --


def test_prompt_separates_disagreement_structures_by_field_name():
    # perf/synthesizer-hybrid-phaseb-wire: claim_disagreements[] is no
    # longer an LLM-authored structure at all -- only the minimal
    # claim_disagreements_semantic override is -- so disagreements[]
    # (legacy, free-text) is the only structured disagreement list the
    # prompt still asks the LLM to author field-by-field.
    prompt = behavior_prompt()
    assert (
        "trusted_conclusion.disagreements[] is the only free-text "
        "structured disagreement list you author directly"
    ) in prompt
    assert "there is no claim_disagreements[] inside trusted_conclusion" in prompt
    assert "positions[] uses the field 'model' (never 'provider')" in prompt
    assert (
        "Never put disagreement_type, impact_on_verdict or "
        "referee_resolution anywhere in trusted_conclusion.disagreements[]"
    ) in prompt
    assert (
        "those fields belong only to "
        "claim_analysis.claim_disagreements_semantic"
    ) in prompt


def test_prompt_no_longer_uses_the_ambiguous_disagreement_instruction():
    prompt = behavior_prompt()
    assert "For every real disagreement, include both provider positions" not in prompt


def test_prompt_states_traceable_claim_invariants():
    prompt = behavior_prompt()
    assert (
        "a provider can never appear in both supporting_models and "
        "disputing_models for the same claim"
    ) in prompt
    assert "every provider named in support[] must also appear in supporting_models" in prompt
    assert "every provider named in dispute[] must also appear in disputing_models" in prompt
    assert (
        "never set status 'supported' based on supporting_models alone "
        "without a matching support excerpt"
    ) in prompt
    assert (
        "if assessment.status is 'disputed', disputing_models must "
        "contain at least one provider"
    ) in prompt


def test_schema_descriptions_distinguish_disagreement_structures():
    schema_text = json.dumps(SynthesisBundleV3.model_json_schema())
    assert "belongs to trusted_conclusion.disagreements" in schema_text
    assert "belongs to trusted_conclusion.claim_disagreements" in schema_text
    assert "cross-checked provider support" in schema_text
    assert "never set 'supported' from supporting_models alone" in schema_text
