"""Tests for deterministic sentence_index -> response_excerpt resolution
(PATCH D1, feature/deterministic-excerpt-sentence-index).

Covers the resolution algorithm directly (_resolve_claim_analysis_wire /
ClaimSupportWire / ClaimAnalysisWireV1), independent of any real API call,
plus end-to-end Synthesizer.synthesize() runs for the initial/repair
stability guarantee (the same sentence map must be reused, never
recomputed, across initial and repair) and the salvage fallback when both
attempts are invalid.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.synthesizer import (  # noqa: E402
    ClaimAnalysisWireV1,
    ClaimSupportWire,
    RESPONSE_EXCERPT_MAX_LENGTH,
    Synthesizer,
    SynthesisWireBundleV1,
    _repair_diagnostic_instruction,
    _resolve_claim_analysis_wire,
    _safe_repair_validation_error,
)
from providers.traceability_schema import (  # noqa: E402
    ClaimSupport,
    validate_claim_analysis,
)


def _wire_judgment(providers):
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


def _wire_claim(claim_id, provider, sentence_index, response_id=None, status="supported"):
    return {
        "id": claim_id,
        "text": "A claim under test.",
        "claim_type": "fact",
        "originating_models": [provider],
        "supporting_models": [provider],
        "disputing_models": [],
        "support": [
            {
                "provider": provider,
                "sentence_index": sentence_index,
                "provider_response_id": response_id or provider,
            }
        ],
        "dispute": [],
        "citation_ids": [],
        "assessment": {"status": status, "reason": "Test fixture."},
        "judgment": _wire_judgment([provider]),
    }


def _wire_analysis(claims, execution_mode="LIVE"):
    return ClaimAnalysisWireV1.model_validate(
        {
            "schema_version": "3.0",
            "execution_mode": execution_mode,
            "claims": claims,
        }
    )


def _answer(provider, text, status="LIVE", response_id=None):
    return {
        "id": provider,
        "provider_key": provider,
        "provider_response_id": response_id or provider,
        "label": provider,
        "provider": provider,
        "provider_status": status,
        "text": text,
    }


def _resolve_and_validate(wire, sentences_by_provider, answers, execution_mode="LIVE"):
    resolved, _judgments = _resolve_claim_analysis_wire(wire, sentences_by_provider)
    return validate_claim_analysis(resolved, answers, [], execution_mode)


# --- K: valid index resolves the exact response_excerpt --------------------


def test_k_valid_index_resolves_exact_response_excerpt():
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 1)])
    sentences_by_provider = {"openai": ["First sentence.", "Second sentence."]}
    resolved, _judgments = _resolve_claim_analysis_wire(wire, sentences_by_provider)
    assert resolved["claims"][0]["support"][0]["response_excerpt"] == (
        "Second sentence."
    )


# --- L: duplicate sentence text at two indices resolves independently ------


def test_l_duplicate_sentence_at_two_indices_both_valid_and_distinct():
    sentences_by_provider = {
        "openai": ["Same sentence.", "Other detail.", "Same sentence."]
    }
    wire = _wire_analysis(
        [
            _wire_claim("claim_a", "openai", 0),
            _wire_claim("claim_b", "openai", 2),
        ]
    )
    resolved, _judgments = _resolve_claim_analysis_wire(wire, sentences_by_provider)
    assert resolved["claims"][0]["support"][0]["response_excerpt"] == (
        "Same sentence."
    )
    assert resolved["claims"][1]["support"][0]["response_excerpt"] == (
        "Same sentence."
    )
    # Each resolves independently by its own position, not by a shared
    # text-identity lookup.
    assert resolved["claims"][0]["id"] != resolved["claims"][1]["id"]


# --- M: index out of range fails ---------------------------------------


def test_m_index_out_of_range_fails():
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 5)])
    sentences_by_provider = {"openai": ["Only sentence."]}
    with pytest.raises(ValueError, match="sentence index is out of range"):
        _resolve_claim_analysis_wire(wire, sentences_by_provider)


# --- N: negative index fails at the wire schema level -----------------


def test_n_negative_index_rejected_by_wire_schema():
    with pytest.raises(ValidationError):
        ClaimSupportWire.model_validate(
            {
                "provider": "openai",
                "sentence_index": -1,
                "provider_response_id": "openai",
            }
        )


# --- O: wrong provider (attribution) fails at the wire schema level -------


def test_o_support_provider_not_in_supporting_models_fails():
    claim = _wire_claim("claim_1", "openai", 0)
    claim["supporting_models"] = ["gemini"]
    with pytest.raises(
        ValidationError, match="support excerpts require a supporting provider"
    ):
        _wire_analysis([claim])


# --- P: provider absent from this execution fails resolution --------------


def test_p_provider_not_available_in_execution_fails():
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 0)])
    # gemini participated in the broader run, but openai (the claim's
    # provider) has no sentence list here -- e.g. it FAILED and was
    # excluded before sentences_by_provider was built.
    sentences_by_provider = {"gemini": ["Gemini sentence."]}
    with pytest.raises(
        ValueError, match="sentence provider is not available in this execution"
    ):
        _resolve_claim_analysis_wire(wire, sentences_by_provider)


# --- Q: provider_response_id mismatch fails downstream validation ---------


def test_q_provider_response_id_mismatch_fails():
    wire = _wire_analysis(
        [_wire_claim("claim_1", "openai", 0, response_id="wrong-id")]
    )
    sentences_by_provider = {"openai": ["Caching helps."]}
    answers = [_answer("openai", "Caching helps.")]
    with pytest.raises(ValueError, match="does not match provider"):
        _resolve_and_validate(wire, sentences_by_provider, answers)


# --- R/S: support and dispute both resolve and pass validation ------------


def test_r_support_item_passes_full_validation():
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 0)])
    sentences_by_provider = {"openai": ["Caching helps."]}
    answers = [_answer("openai", "Caching helps.")]
    parsed = _resolve_and_validate(wire, sentences_by_provider, answers)
    assert parsed.claims[0].support[0].response_excerpt == "Caching helps."


def test_s_dispute_item_passes_full_validation():
    claim = {
        "id": "claim_1",
        "text": "A disputed claim.",
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai"],
        "disputing_models": ["gemini"],
        "support": [
            {"provider": "openai", "sentence_index": 0, "provider_response_id": "openai"}
        ],
        "dispute": [
            {"provider": "gemini", "sentence_index": 0, "provider_response_id": "gemini"}
        ],
        "citation_ids": [],
        "assessment": {"status": "disputed", "reason": "They disagree."},
        "judgment": _wire_judgment(["openai", "gemini"]),
    }
    wire = _wire_analysis([claim])
    sentences_by_provider = {
        "openai": ["Ten requests per minute."],
        "gemini": ["Twenty requests per minute."],
    }
    answers = [
        _answer("openai", "Ten requests per minute."),
        _answer("gemini", "Twenty requests per minute."),
    ]
    parsed = _resolve_and_validate(wire, sentences_by_provider, answers)
    assert parsed.claims[0].dispute[0].response_excerpt == (
        "Twenty requests per minute."
    )


# --- T: same input/index always resolves to the same excerpt --------------


def test_t_same_input_and_index_always_resolve_to_the_same_excerpt():
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 0)])
    sentences_by_provider = {"openai": ["Caching helps.", "It reduces load."]}
    first, _judgments1 = _resolve_claim_analysis_wire(wire, sentences_by_provider)
    second, _judgments2 = _resolve_claim_analysis_wire(wire, sentences_by_provider)
    assert (
        first["claims"][0]["support"][0]["response_excerpt"]
        == second["claims"][0]["support"][0]["response_excerpt"]
        == "Caching helps."
    )


# --- U/V/W: end-to-end via Synthesizer.synthesize(), no real API calls ----


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


OPENAI_TEXT = "Caching reduces repeated network calls. The current rate limit is ten."
GEMINI_TEXT = "Caching also reduces repeated network calls. The rate limit is twenty."


def _bundle(sentence_index):
    return {
        "trusted_conclusion": _base_trusted_conclusion(),
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [_wire_claim("claim_1", "openai", sentence_index)],
        },
    }


def _answers_for_synth():
    return [
        _answer("openai", OPENAI_TEXT),
        _answer("gemini", GEMINI_TEXT),
    ]


class FakeCompletions:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0
        self.requests = []

    async def create(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=next(self.outputs)))
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
            model="gpt-5.4-mini",
        )


def _synthesizer(outputs):
    synth = Synthesizer.__new__(Synthesizer)
    completions = FakeCompletions(outputs)
    synth.available = True
    synth._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return synth, completions


def _run(synth, *, query_id):
    return asyncio.run(
        synth.synthesize(
            "Does caching help?",
            _answers_for_synth(),
            "en",
            correlation_id=query_id,
        )
    )


def test_u_initial_valid_sentence_index_succeeds_without_repair():
    synth, completions = _synthesizer([json.dumps(_bundle(0))])
    result = _run(synth, query_id="sentence-index-u")

    assert completions.calls == 1
    assert result["repair_attempted"] is False
    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["claims"][0]["support"][0]["response_excerpt"] == (
        "Caching reduces repeated network calls."
    )


def test_v_initial_invalid_repair_reuses_the_same_sentence_map_and_succeeds():
    synth, completions = _synthesizer(
        [json.dumps(_bundle(9)), json.dumps(_bundle(0))]
    )
    result = _run(synth, query_id="sentence-index-v")

    assert completions.calls == 2
    assert result["repair_attempted"] is True
    assert result["claim_analysis_status"] == "SUCCESS"

    initial_payload = json.loads(completions.requests[0]["messages"][1]["content"])
    repair_payload = json.loads(completions.requests[1]["messages"][1]["content"])
    # The sentence map handed to repair is byte-identical to the one shown
    # during the initial call -- computed once per request, never
    # recomputed (spec section 2: initial/repair stability).
    assert repair_payload["provider_responses"] == initial_payload["provider_responses"]

    repair_system = completions.requests[1]["messages"][0]["content"]
    assert "Replace each invalid sentence_index" in repair_system


def test_w_initial_and_repair_both_invalid_falls_back_to_salvage():
    synth, completions = _synthesizer(
        [json.dumps(_bundle(9)), json.dumps(_bundle(9))]
    )
    result = _run(synth, query_id="sentence-index-w")

    assert completions.calls == 2
    assert result["repair_attempted"] is True
    assert result["claim_analysis_status"] == "FAILED"
    assert result["claims"] == []
    assert result["text"] == "A validated combined answer."


# --- D1 hotfix: claim_analysis remains a top-level wire sibling ----------


def _bundle_with_nested_claim_analysis(sentence_index=0):
    payload = _bundle(sentence_index)
    payload["trusted_conclusion"]["claim_analysis"] = payload.pop(
        "claim_analysis"
    )
    return payload


def _nested_claim_analysis_validation_error():
    with pytest.raises(ValidationError) as caught:
        SynthesisWireBundleV1.model_validate(
            _bundle_with_nested_claim_analysis()
        )
    return caught.value


def test_claim_analysis_top_level_wire_bundle_passes():
    bundle = SynthesisWireBundleV1.model_validate(_bundle(0))
    assert bundle.claim_analysis.claims[0].support[0].sentence_index == 0


def test_nested_claim_analysis_reproduces_production_validation_errors():
    errors = _nested_claim_analysis_validation_error().errors()
    pairs = {(tuple(item["loc"]), item["type"]) for item in errors}
    assert (
        ("trusted_conclusion", "claim_analysis"),
        "extra_forbidden",
    ) in pairs
    assert (("claim_analysis",), "missing") in pairs


def test_initial_prompt_requires_exactly_two_top_level_keys():
    synth, completions = _synthesizer([json.dumps(_bundle(0))])
    _run(synth, query_id="claim-analysis-prompt")

    system = completions.requests[0]["messages"][0]["content"]
    assert (
        "Return exactly two top-level keys: trusted_conclusion and "
        "claim_analysis"
    ) in system
    assert "claim_analysis is NOT part of trusted_conclusion" in system
    assert "Never nest claim_analysis inside trusted_conclusion" in system


def test_repair_classifier_recognizes_production_nesting_pattern():
    instruction = _repair_diagnostic_instruction(
        _nested_claim_analysis_validation_error()
    )
    assert "Move claim_analysis out of trusted_conclusion" in instruction
    assert "sibling to trusted_conclusion" in instruction
    assert "Do not change its content" in instruction


def test_nested_initial_repairs_top_level_and_resolves_sentence_index():
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_with_nested_claim_analysis()),
            json.dumps(_bundle(0)),
        ]
    )
    result = _run(synth, query_id="claim-analysis-repair")

    assert completions.calls == 2
    repair_system = completions.requests[1]["messages"][0]["content"]
    assert "Move claim_analysis out of trusted_conclusion" in repair_system
    assert result["repair_attempted"] is True
    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["claims"][0]["support"][0]["response_excerpt"] == (
        "Caching reduces repeated network calls."
    )


def test_unrelated_validation_error_gets_no_top_level_instruction():
    invalid = _bundle(0)
    invalid["unexpected"] = "not user content"
    with pytest.raises(ValidationError) as caught:
        SynthesisWireBundleV1.model_validate(invalid)

    assert _repair_diagnostic_instruction(caught.value) == ""


def test_repair_validation_diagnostics_do_not_include_rejected_values():
    secret = "SECRET_PROVIDER_OUTPUT_MUST_NOT_LEAK"
    invalid = _bundle(0)
    invalid["trusted_conclusion"]["claim_analysis"] = {"text": secret}
    invalid.pop("claim_analysis")
    with pytest.raises(ValidationError) as caught:
        SynthesisWireBundleV1.model_validate(invalid)

    diagnostic = _safe_repair_validation_error(caught.value)
    assert secret not in diagnostic
    assert "input" not in diagnostic
    assert "extra_forbidden" in diagnostic
    assert "missing" in diagnostic


# --- D1.1: bounded sentence segments survive public validation ------------


def _long_provider_text():
    return "a" * 300 + "; " + "b" * 300 + "."


def _long_answers_for_synth():
    return [
        _answer("openai", _long_provider_text()),
        _answer("gemini", GEMINI_TEXT),
    ]


def _run_with_answers(synth, answers, *, query_id):
    return asyncio.run(
        synth.synthesize(
            "Does caching help?",
            answers,
            "en",
            correlation_id=query_id,
        )
    )


def test_long_sentence_chunk_resolves_exact_bounded_support_excerpt():
    text = _long_provider_text()
    sentences = ["a" * 300 + ";", "b" * 300 + "."]
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 1)])
    parsed = _resolve_and_validate(
        wire,
        {"openai": sentences},
        [_answer("openai", text)],
    )

    excerpt = parsed.claims[0].support[0].response_excerpt
    assert excerpt == sentences[1]
    assert excerpt in text
    assert len(excerpt) <= RESPONSE_EXCERPT_MAX_LENGTH


def test_long_sentence_chunk_resolves_exact_bounded_dispute_excerpt():
    claim = _wire_claim("claim_1", "openai", 1, status="disputed")
    claim["supporting_models"] = []
    claim["disputing_models"] = ["openai"]
    claim["support"] = []
    claim["dispute"] = [
        {
            "provider": "openai",
            "sentence_index": 1,
            "provider_response_id": "openai",
        }
    ]
    wire = _wire_analysis([claim])
    text = _long_provider_text()
    parsed = _resolve_and_validate(
        wire,
        {"openai": ["a" * 300 + ";", "b" * 300 + "."]},
        [_answer("openai", text)],
    )

    excerpt = parsed.claims[0].dispute[0].response_excerpt
    assert excerpt == "b" * 300 + "."
    assert len(excerpt) <= RESPONSE_EXCERPT_MAX_LENGTH


def test_initial_long_sentence_produces_no_string_too_long():
    synth, completions = _synthesizer([json.dumps(_bundle(1))])
    result = _run_with_answers(
        synth,
        _long_answers_for_synth(),
        query_id="bounded-initial",
    )

    assert completions.calls == 1
    assert result["repair_attempted"] is False
    excerpt = result["claims"][0]["support"][0]["response_excerpt"]
    assert excerpt == "b" * 300 + "."
    assert len(excerpt) <= RESPONSE_EXCERPT_MAX_LENGTH


def test_repair_reuses_identical_bounded_sentence_map():
    synth, completions = _synthesizer(
        [json.dumps(_bundle(9)), json.dumps(_bundle(1))]
    )
    result = _run_with_answers(
        synth,
        _long_answers_for_synth(),
        query_id="bounded-repair",
    )

    initial_payload = json.loads(
        completions.requests[0]["messages"][1]["content"]
    )
    repair_payload = json.loads(
        completions.requests[1]["messages"][1]["content"]
    )
    assert repair_payload["provider_responses"] == initial_payload[
        "provider_responses"
    ]
    exposed = initial_payload["provider_responses"][0]["sentences"]
    assert max(len(item["text"]) for item in exposed) <= (
        RESPONSE_EXCERPT_MAX_LENGTH
    )
    assert result["claim_analysis_status"] == "SUCCESS"


def test_public_response_excerpt_max_length_validator_remains_active():
    with pytest.raises(ValidationError) as caught:
        ClaimSupport.model_validate(
            {
                "provider": "openai",
                "response_excerpt": "x" * (RESPONSE_EXCERPT_MAX_LENGTH + 1),
                "response_reference": {"provider_response_id": "openai"},
            }
        )
    assert any(
        item["loc"] == ("response_excerpt",)
        and item["type"] == "string_too_long"
        for item in caught.value.errors()
    )


# --- X: the public excerpt-in-response validator stays active -------------


def test_x_resolved_excerpt_still_passes_the_public_validator():
    # Resolution builds response_excerpt by direct lookup, but
    # validate_claim_analysis (unchanged) still independently re-checks
    # that the excerpt is a real substring of the provider response --
    # the double guarantee required by spec section 7.
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 0)])
    sentences_by_provider = {"openai": ["Caching helps."]}
    answers = [_answer("openai", "Caching helps.")]
    parsed = _resolve_and_validate(wire, sentences_by_provider, answers)
    assert parsed.claims[0].support[0].response_excerpt in "Caching helps."


# --- Y/Z: citation provenance and LIVE/DEMO separation are unaffected -----


def test_y_citation_provenance_still_enforced_after_resolution():
    claim = _wire_claim("claim_1", "openai", 0)
    claim["citation_ids"] = ["citation_missing"]
    wire = _wire_analysis([claim])
    sentences_by_provider = {"openai": ["Caching helps."]}
    answers = [_answer("openai", "Caching helps.")]
    with pytest.raises(ValueError, match="unknown citation"):
        _resolve_and_validate(wire, sentences_by_provider, answers)


def test_z_live_demo_separation_still_enforced_after_resolution():
    wire = _wire_analysis([_wire_claim("claim_1", "openai", 0)], execution_mode="DEMO")
    sentences_by_provider = {"openai": ["Caching helps."]}
    answers = [_answer("openai", "Caching helps.", status="MOCK")]
    with pytest.raises(ValueError, match="execution mode"):
        _resolve_and_validate(wire, sentences_by_provider, answers, execution_mode="LIVE")
