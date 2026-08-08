"""Diagnostic-only tests for post-Pydantic ValueError classification.

These reproduce, offline and without any real API call, the exact
"Pydantic valid -> raw ValueError" failure shape observed in a real
production trace (query_id bca253ac-15fd-40bd-9d0c-65ca49d751aa): the JSON
passes SynthesisBundleV3 schema validation, but a business-rule check that
runs *after* model_validate() rejects it. Before this patch, every such
failure was logged only as the generic string "ValueError" with no way to
tell which check fired. These tests confirm the new
synthesis_post_validation_error log line resolves that ambiguity without
ever logging the exception message, prompt, provider text, excerpts, hints,
URLs or citation content -- and that application behavior (SUCCESS/FAILED,
salvage, repair) is unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import TrustedConclusionV21  # noqa: E402
from providers.synthesizer import (  # noqa: E402
    Synthesizer,
    _classify_post_validation_error,
    _log_parse_failure,
)


# --- _classify_post_validation_error: direct mapping-table coverage -------


@pytest.mark.parametrize(
    "message, expected_code, expected_stage",
    [
        (
            "Conclusion references providers outside the current execution: mistral",
            "provider_not_participating",
            "parse_structured_conclusion",
        ),
        (
            "claim matrix must contain one position for every participating "
            "provider: missing mistral",
            "claim_matrix_missing_participating_provider",
            "parse_structured_conclusion",
        ),
        (
            "a single-provider conclusion must report low model agreement",
            "single_provider_agreement_not_low",
            "parse_structured_conclusion",
        ),
        (
            "claim analysis execution mode does not match comparison",
            "execution_mode_mismatch",
            "validate_claim_analysis",
        ),
        (
            "claim evidence crosses LIVE and DEMO execution modes",
            "execution_mode_mismatch",
            "validate_claim_analysis",
        ),
        (
            "claim references a FAILED or absent provider",
            "provider_failed",
            "validate_claim_analysis",
        ),
        (
            "claim excerpt is not present in provider response",
            "claim_excerpt_not_in_provider_response",
            "validate_claim_analysis",
        ),
        (
            "claim dispute excerpt is not present in provider response",
            "claim_excerpt_not_in_provider_response",
            "validate_claim_analysis",
        ),
        (
            "claim response reference does not match provider",
            "provider_response_id_mismatch",
            "validate_claim_analysis",
        ),
        (
            "claim dispute response reference does not match provider",
            "provider_response_id_mismatch",
            "validate_claim_analysis",
        ),
        (
            "claim response hint is not present in response",
            "hint_not_in_provider_response",
            "validate_claim_analysis",
        ),
        (
            "claim dispute response hint is not present in response",
            "hint_not_in_provider_response",
            "validate_claim_analysis",
        ),
        (
            "claim references an unknown citation",
            "unknown_citation_reference",
            "validate_claim_analysis",
        ),
        (
            "citation provenance does not match claim providers",
            "citation_provenance_mismatch",
            "validate_claim_analysis",
        ),
        (
            "claim sentence index is out of range for the provider response",
            "sentence_index_out_of_range",
            "resolve_claim_analysis_wire",
        ),
        (
            "claim sentence provider is not available in this execution",
            "sentence_provider_not_available",
            "resolve_claim_analysis_wire",
        ),
        (
            "claim sentence resolution failed unexpectedly",
            "sentence_resolution_failed",
            "resolve_claim_analysis_wire",
        ),
        (
            "Trusted Conclusion references unknown claim IDs: claim_9",
            "unknown_claim_reference",
            "validate_conclusion_claim_references",
        ),
        (
            "Claim matrix references unknown evidence IDs: response-x",
            "unknown_evidence_reference",
            "validate_conclusion_claim_references",
        ),
        (
            "Disagreement position references evidence from another provider",
            "disagreement_evidence_provider_mismatch",
            "validate_conclusion_claim_references",
        ),
    ],
)
def test_classify_known_post_validation_prefixes(
    message,
    expected_code,
    expected_stage,
):
    code, stage = _classify_post_validation_error(ValueError(message))
    assert code == expected_code
    assert stage == expected_stage


def test_classify_unrecognized_value_error_falls_back_safely():
    code, stage = _classify_post_validation_error(
        ValueError("Some future check message never seen before.")
    )
    assert code == "other_post_pydantic_validation_error"
    assert stage == "unknown"


def test_classify_non_value_error_falls_back_safely():
    code, stage = _classify_post_validation_error(KeyError("boom"))
    assert code == "other_post_pydantic_validation_error"
    assert stage == "unknown"


def test_enrichment_tagged_validation_error_gets_supplementary_code(caplog):
    try:
        TrustedConclusionV21.model_validate({})
    except ValidationError as exc:
        error = exc
    else:  # pragma: no cover - defensive, should always raise
        raise AssertionError("expected a ValidationError")
    error._diagnostic_stage = "enrich_conclusion"

    with caplog.at_level(logging.WARNING):
        _log_parse_failure("diag-enrich", "initial", "gpt-5.4-mini", error)

    assert "synthesis_validation_error query_id=diag-enrich stage=initial" in caplog.text
    event = next(
        line
        for line in caplog.text.splitlines()
        if "synthesis_post_validation_error" in line
    )
    assert "query_id=diag-enrich" in event
    assert "stage=initial" in event
    assert "validation_stage=enrich_conclusion" in event
    assert "diagnostic_code=conclusion_enrichment_validation_failed" in event
    assert "error_type=ValidationError" in event


def test_unrelated_validation_error_gets_no_supplementary_code(caplog):
    try:
        TrustedConclusionV21.model_validate({})
    except ValidationError as exc:
        error = exc
    else:  # pragma: no cover - defensive, should always raise
        raise AssertionError("expected a ValidationError")

    with caplog.at_level(logging.WARNING):
        _log_parse_failure("diag-plain", "initial", "gpt-5.4-mini", error)

    assert "synthesis_post_validation_error" not in caplog.text


# --- End-to-end: real Synthesizer.synthesize() runs, no real API calls ----


def _base_trusted_conclusion(**overrides):
    payload = {
        "schema_version": "2.0",
        "final_answer": "A validated combined answer.",
        "agreements": [],
        "disagreements": [],
        "strongest_evidence": [],
        "remaining_uncertainties": [],
        "unsupported_claims": [],
        "confidence": {
            "level": "medium",
            "reason": "Evidence is limited to the current provider panel.",
            "factors": {
                "model_agreement": "medium",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "referee_reasoning": "The panel provides partial coverage.",
        "what_could_change_the_verdict": [],
    }
    payload.update(overrides)
    return payload


def _judgment(providers):
    return {
        "importance": "medium",
        "referee_assessment": "Assessment for testing.",
        "evidence_limitations": [],
        "partially_supported_by": [],
        "provider_judgments": [
            {"provider": provider, "summary": f"{provider} summary for testing."}
            for provider in providers
        ],
    }


def _valid_bundle():
    return {
        "trusted_conclusion": _base_trusted_conclusion(),
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [],
        },
    }


def _bundle_with_wire_claim_matrix_field():
    # claim_matrix is no longer part of the LLM-facing wire contract
    # (perf/synthesizer-hybrid-phaseb-wire): supplying it must be rejected
    # structurally (extra_forbidden), never reach the old semantic
    # "one position per participating provider" check.
    conclusion = _base_trusted_conclusion(
        claim_matrix=[
            {
                "claim_id": "claim_1",
                "claim": "Caching reduces repeated work.",
                "importance": "medium",
                "provider_positions": [
                    {
                        "provider": "openai",
                        "display_name": "ChatGPT",
                        "position": "supports",
                        "summary": "OpenAI supports this claim.",
                        "evidence_refs": [],
                        "confidence": "medium",
                    }
                ],
                "agreement_level": "partial_consensus",
                "referee_assessment": "Only OpenAI addressed this point.",
                "evidence_limitations": [],
            }
        ],
    )
    return {
        "trusted_conclusion": conclusion,
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [],
        },
    }


def _bundle_unknown_claim_reference():
    conclusion = _base_trusted_conclusion(
        agreements=[
            {
                "id": "agreement_1",
                "claim": "Both providers discuss caching.",
                "supporting_models": ["openai", "gemini"],
                "strength": "moderate",
                "reason": "Both mention caching benefits.",
                "supporting_claim_ids": ["claim_ghost"],
            }
        ],
    )
    return {
        "trusted_conclusion": conclusion,
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [
                {
                    "id": "claim_real",
                    "text": "Caching reduces repeated work.",
                    "claim_type": "fact",
                    "originating_models": ["openai"],
                    "supporting_models": [],
                    "disputing_models": [],
                    "support": [],
                    "dispute": [],
                    "citation_ids": [],
                    "assessment": {
                        "status": "weak",
                        "reason": "Not independently corroborated.",
                    },
                    "judgment": _judgment(["openai"]),
                }
            ],
        },
    }


def _bundle_sentence_index_out_of_range():
    return {
        "trusted_conclusion": _base_trusted_conclusion(),
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [
                {
                    "id": "claim_fabricated",
                    "text": "A fabricated claim.",
                    "claim_type": "fact",
                    "originating_models": ["openai"],
                    "supporting_models": ["openai"],
                    "disputing_models": [],
                    "support": [
                        {
                            "provider": "openai",
                            # _answers() gives openai a single-sentence
                            # response (index 0 only) -- 5 is out of range.
                            "sentence_index": 5,
                            "provider_response_id": "openai",
                        }
                    ],
                    "dispute": [],
                    "citation_ids": [],
                    "assessment": {
                        "status": "supported",
                        "reason": "OpenAI directly supports this.",
                    },
                    "judgment": _judgment(["openai"]),
                }
            ],
        },
    }


def _answers():
    return [
        {
            "id": "model-a",
            "provider_key": "openai",
            "provider_response_id": "openai",
            "label": "ChatGPT",
            "provider": "OpenAI",
            "provider_status": "LIVE",
            "text": "SECRET_OPENAI_RESPONSE_TEXT describes caching behavior.",
        },
        {
            "id": "model-c",
            "provider_key": "gemini",
            "provider_response_id": "gemini",
            "label": "Gemini",
            "provider": "Google DeepMind",
            "provider_status": "LIVE",
            "text": "SECRET_GEMINI_RESPONSE_TEXT describes caching behavior.",
        },
    ]


class FakeCompletions:
    def __init__(self, outputs):
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
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
            model="gpt-5.4-mini",
        )


def _synthesizer(outputs):
    synth = Synthesizer.__new__(Synthesizer)
    completions = FakeCompletions(outputs)
    synth.available = True
    synth._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return synth, completions


def _run(synth, *, query_id):
    return asyncio.run(
        synth.synthesize(
            "SECRET_USER_PROMPT about caching.",
            _answers(),
            "en",
            correlation_id=query_id,
        )
    )


_FORBIDDEN_CONTENT = (
    "SECRET_USER_PROMPT",
    "SECRET_OPENAI_RESPONSE_TEXT",
    "SECRET_GEMINI_RESPONSE_TEXT",
    "This exact text never appears anywhere",
    "claim_ghost",
)


def test_a_claim_matrix_wire_field_is_structurally_rejected(caplog):
    # perf/synthesizer-hybrid-phaseb-wire: claim_matrix is no longer part
    # of the wire contract, so a wire payload that includes it can never
    # reach the old semantic "one position per participating provider"
    # check (diagnostic_code=claim_matrix_missing_participating_provider,
    # stage=parse_structured_conclusion) -- it is rejected structurally
    # (extra_forbidden) before that stage even runs.
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_with_wire_claim_matrix_field()),
            json.dumps(_valid_bundle()),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result = _run(synth, query_id="diag-a")

    assert completions.calls == 2
    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["repair_attempted"] is True

    event = next(
        line
        for line in caplog.text.splitlines()
        if "synthesis_validation_error" in line
    )
    assert "query_id=diag-a" in event
    assert "stage=initial" in event
    assert '"code":"pydantic.extra_forbidden"' in event
    assert (
        "synthesis_post_validation_error" not in caplog.text
    )
    for forbidden in _FORBIDDEN_CONTENT:
        assert forbidden not in caplog.text


def test_b_unknown_claim_reference_is_diagnosed(caplog):
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_unknown_claim_reference()),
            json.dumps(_valid_bundle()),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result = _run(synth, query_id="diag-b")

    assert completions.calls == 2
    assert result["claim_analysis_status"] == "SUCCESS"

    event = next(
        line
        for line in caplog.text.splitlines()
        if "synthesis_post_validation_error" in line
    )
    assert "query_id=diag-b" in event
    assert "stage=initial" in event
    assert "validation_stage=validate_conclusion_claim_references" in event
    assert "diagnostic_code=unknown_claim_reference" in event
    assert "error_type=ValueError" in event
    for forbidden in _FORBIDDEN_CONTENT:
        assert forbidden not in caplog.text


def test_c_sentence_index_out_of_range_is_diagnosed(caplog):
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_sentence_index_out_of_range()),
            json.dumps(_valid_bundle()),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result = _run(synth, query_id="diag-c")

    assert completions.calls == 2
    assert result["claim_analysis_status"] == "SUCCESS"

    event = next(
        line
        for line in caplog.text.splitlines()
        if "synthesis_post_validation_error" in line
    )
    assert "query_id=diag-c" in event
    assert "stage=initial" in event
    assert "validation_stage=resolve_claim_analysis_wire" in event
    assert "diagnostic_code=sentence_index_out_of_range" in event
    assert "error_type=ValueError" in event
    for forbidden in _FORBIDDEN_CONTENT:
        assert forbidden not in caplog.text


def test_repair_stage_is_diagnosed_independently_of_initial(caplog):
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_sentence_index_out_of_range()),
            json.dumps(_bundle_sentence_index_out_of_range()),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result = _run(synth, query_id="diag-repair")

    assert completions.calls == 2
    assert result["claim_analysis_status"] == "FAILED"
    assert result["text"] == "A validated combined answer."

    events = [
        line
        for line in caplog.text.splitlines()
        if "synthesis_post_validation_error" in line
    ]
    stages = {
        "initial": next(line for line in events if "stage=initial" in line),
        "repair": next(line for line in events if "stage=repair" in line),
    }
    for stage_name, event in stages.items():
        assert f"query_id=diag-repair" in event
        assert "diagnostic_code=sentence_index_out_of_range" in event
    for forbidden in _FORBIDDEN_CONTENT:
        assert forbidden not in caplog.text
