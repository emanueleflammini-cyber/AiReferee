"""Tests for the exact-excerpt prompt fix and diagnostic-aware repair.

Covers the fix for the real production failure class
(diagnostic_code=claim_excerpt_not_in_provider_response repeating on both
initial and repair, query_id bebf8780-0c8e-4e70-9d2d-5f0a3c0493f5): the
validator itself (validate_claim_analysis/_excerpt_in_response) is
unchanged -- these tests confirm it stays exact-substring, case-sensitive,
non-fuzzy -- while the prompt now states the contiguous/verbatim/
no-translation rule unambiguously, and the repair call now receives a
targeted, non-content-bearing instruction when the diagnostic_code is
excerpt/hint/reference related.
"""
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

from providers.synthesizer import (  # noqa: E402
    Synthesizer,
    _repair_diagnostic_instruction,
    _system_prompt,
)
from providers.traceability_schema import validate_claim_analysis  # noqa: E402


# --- validator behavior: unchanged, exact-substring, non-fuzzy -----------

OPENAI_TEXT = (
    "Caching reduces repeated network calls. The current rate limit is "
    "ten requests per minute."
)
GEMINI_TEXT = (
    "Caching also reduces repeated network calls. The current rate limit "
    "is twenty requests per minute."
)


def answer(provider, text, status="LIVE"):
    labels = {"openai": "ChatGPT", "gemini": "Gemini"}
    names = {"openai": "OpenAI", "gemini": "Google DeepMind"}
    return {
        "id": {"openai": "model-a", "gemini": "model-c"}[provider],
        "provider_response_id": provider,
        "provider_key": provider,
        "label": labels[provider],
        "provider": names[provider],
        "provider_status": status,
        "text": text,
        "citations": [],
    }


def support(provider, excerpt, response_id=None):
    return {
        "provider": provider,
        "response_excerpt": excerpt,
        "response_reference": {
            "provider_response_id": response_id or provider,
        },
    }


def claim_analysis(claims):
    return {"schema_version": "3.0", "execution_mode": "LIVE", "claims": claims}


def supported_claim(excerpt, provider="openai"):
    return {
        "id": "claim_1",
        "text": "Caching reduces repeated network calls.",
        "claim_type": "fact",
        "originating_models": [provider],
        "supporting_models": [provider],
        "disputing_models": [],
        "support": [support(provider, excerpt)],
        "dispute": [],
        "citation_ids": [],
        "assessment": {
            "status": "supported",
            "reason": f"{provider} directly states this.",
        },
    }


def disputed_claim(excerpt, provider="gemini"):
    return {
        "id": "claim_2",
        "text": "The current rate limit is disputed.",
        "claim_type": "fact",
        "originating_models": ["openai", provider],
        "supporting_models": ["openai"],
        "disputing_models": [provider],
        "support": [support("openai", "ten requests per minute")],
        "dispute": [support(provider, excerpt)],
        "citation_ids": [],
        "assessment": {
            "status": "disputed",
            "reason": f"{provider} states a different current limit.",
        },
    }


ANSWERS = [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)]


def test_1_exact_contiguous_substring_passes():
    parsed = validate_claim_analysis(
        claim_analysis([supported_claim("Caching reduces repeated network calls.")]),
        ANSWERS,
        [],
        "LIVE",
    )
    assert parsed.claims[0].support[0].response_excerpt == (
        "Caching reduces repeated network calls."
    )


def test_2_paraphrase_fails():
    claim = supported_claim("Repeated network calls are reduced through caching.")
    with pytest.raises(ValueError, match="excerpt is not present"):
        validate_claim_analysis(claim_analysis([claim]), ANSWERS, [], "LIVE")


def test_3_one_word_modified_fails():
    claim = supported_claim("Caching reduces repeated network requests.")
    with pytest.raises(ValueError, match="excerpt is not present"):
        validate_claim_analysis(claim_analysis([claim]), ANSWERS, [], "LIVE")


def test_4_concatenated_fragments_fail():
    # Real text: "...network calls. The current rate limit is ten..."
    # This excerpt splices the tail of one sentence onto a non-adjacent
    # fragment of the next -- never appears contiguously in OPENAI_TEXT.
    claim = supported_claim("network calls is ten requests per minute")
    with pytest.raises(ValueError, match="excerpt is not present"):
        validate_claim_analysis(claim_analysis([claim]), ANSWERS, [], "LIVE")


def test_5_wrong_provider_excerpt_fails():
    # "Caching also reduces..." is real GEMINI_TEXT, not OPENAI_TEXT
    # (which lacks "also") -- attributing it to openai must fail.
    claim = supported_claim(
        "Caching also reduces repeated network calls.", provider="openai"
    )
    with pytest.raises(ValueError, match="excerpt is not present"):
        validate_claim_analysis(claim_analysis([claim]), ANSWERS, [], "LIVE")


def test_6_correct_dispute_excerpt_passes():
    parsed = validate_claim_analysis(
        claim_analysis([disputed_claim("twenty requests per minute")]),
        ANSWERS,
        [],
        "LIVE",
    )
    assert parsed.claims[0].dispute[0].response_excerpt == (
        "twenty requests per minute"
    )


def test_7_unicode_whitespace_normalization_still_supported():
    claim = supported_claim("Caching  reduces\n repeated   network calls.")
    parsed = validate_claim_analysis(
        claim_analysis([claim]), ANSWERS, [], "LIVE"
    )
    assert parsed.claims[0].support[0].response_excerpt == (
        "Caching  reduces\n repeated   network calls."
    )


def test_no_case_insensitive_or_fuzzy_matching_introduced():
    claim = supported_claim("caching reduces repeated network calls.")
    with pytest.raises(ValueError, match="excerpt is not present"):
        validate_claim_analysis(claim_analysis([claim]), ANSWERS, [], "LIVE")


# --- prompt: exact-excerpt wording + explicit language carve-out ---------


def behavior_prompt(target_name="English"):
    return _system_prompt(
        target_name=target_name,
        audience="professional",
        fmt="paragraph",
        allowed_providers=["openai", "gemini"],
        provider_labels={"openai": "ChatGPT", "gemini": "Gemini"},
        execution_mode="LIVE",
    )


def test_8_translation_rule_explicitly_excludes_the_numbered_sentences():
    prompt = behavior_prompt(target_name="Italian")
    assert "Write every human-readable field in Italian" in prompt
    assert (
        "This translation requirement does not apply to the numbered "
        "sentences supplied in provider_responses[].sentences"
    ) in prompt
    assert "reference material to select from, not output you write" in prompt


def test_9_prompt_states_sentence_index_selection_rule():
    prompt = behavior_prompt()
    assert "set sentence_index to the index" in prompt
    assert "provider_responses[].sentences" in prompt
    assert "Choose exactly one existing sentence per item" in prompt
    assert (
        "never invent, estimate, or reuse an index from a different "
        "provider's sentence list"
    ) in prompt


# --- diagnostic-aware repair instruction: unit-level ----------------------


def test_repair_instruction_selected_for_sentence_index_diagnostic_code():
    instruction = _repair_diagnostic_instruction(
        ValueError(
            "claim sentence index is out of range for the provider response"
        )
    )
    assert "Replace each invalid sentence_index" in instruction
    assert "existing sentence for that provider" in instruction


def test_repair_instruction_selected_for_sentence_provider_diagnostic_code():
    instruction = _repair_diagnostic_instruction(
        ValueError(
            "claim sentence provider is not available in this execution"
        )
    )
    assert "no sentences list in provider_responses" in instruction


def test_repair_instruction_empty_for_unrelated_diagnostic_code():
    instruction = _repair_diagnostic_instruction(
        ValueError(
            "claim matrix must contain one position for every "
            "participating provider"
        )
    )
    assert instruction == ""


# --- end-to-end: real Synthesizer.synthesize() runs, no real API calls ---


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
        "claim_matrix": [],
        "claim_agreements": [],
        "claim_disagreements": [],
    }
    payload.update(overrides)
    return payload


def _valid_bundle():
    return {
        "trusted_conclusion": _base_trusted_conclusion(),
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [],
        },
    }


def wire_support(provider, sentence_index, response_id=None):
    return {
        "provider": provider,
        "sentence_index": sentence_index,
        "provider_response_id": response_id or provider,
    }


def wire_supported_claim(sentence_index, provider="openai"):
    return {
        "id": "claim_1",
        "text": "Caching reduces repeated network calls.",
        "claim_type": "fact",
        "originating_models": [provider],
        "supporting_models": [provider],
        "disputing_models": [],
        "support": [wire_support(provider, sentence_index)],
        "dispute": [],
        "citation_ids": [],
        "assessment": {
            "status": "supported",
            "reason": f"{provider} directly states this.",
        },
    }


def _bundle_bad_sentence_index():
    # OPENAI_TEXT only has sentences 0 and 1 -- 5 is out of range.
    return {
        "trusted_conclusion": _base_trusted_conclusion(),
        "claim_analysis": claim_analysis([wire_supported_claim(5)]),
    }


def _bundle_good_sentence_index():
    # Sentence 0 of OPENAI_TEXT is exactly "Caching reduces repeated
    # network calls."
    return {
        "trusted_conclusion": _base_trusted_conclusion(),
        "claim_analysis": claim_analysis([wire_supported_claim(0)]),
    }


def _bundle_missing_provider_position():
    conclusion = _base_trusted_conclusion(
        claim_matrix=[
            {
                "claim_id": "claim_1",
                "claim": "Caching reduces repeated network calls.",
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


def _answers_for_synth():
    return [
        {
            "id": "model-a",
            "provider_key": "openai",
            "provider_response_id": "openai",
            "label": "ChatGPT",
            "provider": "OpenAI",
            "provider_status": "LIVE",
            "text": OPENAI_TEXT,
        },
        {
            "id": "model-c",
            "provider_key": "gemini",
            "provider_response_id": "gemini",
            "label": "Gemini",
            "provider": "Google DeepMind",
            "provider_status": "LIVE",
            "text": GEMINI_TEXT,
        },
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
            "Does caching help with rate limits?",
            _answers_for_synth(),
            "en",
            correlation_id=query_id,
        )
    )


def _repair_system_content(completions):
    return completions.requests[1]["messages"][0]["content"]


def test_10_initial_invalid_sentence_index_repair_receives_specific_instruction():
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_bad_sentence_index()),
            json.dumps(_bundle_good_sentence_index()),
        ]
    )

    result = _run(synth, query_id="excerpt-repair-1")

    assert completions.calls == 2
    repair_system = _repair_system_content(completions)
    assert "Replace each invalid sentence_index" in repair_system
    assert "existing sentence for that provider" in repair_system
    assert result["claim_analysis_status"] == "SUCCESS"


def test_11_repair_with_valid_sentence_index_succeeds():
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_bad_sentence_index()),
            json.dumps(_bundle_good_sentence_index()),
        ]
    )

    result = _run(synth, query_id="excerpt-repair-2")

    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["claims"][0]["support"][0]["response_excerpt"] == (
        "Caching reduces repeated network calls."
    )
    assert result["repair_attempted"] is True


def test_12_repair_still_invalid_falls_back_to_salvage_unchanged():
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_bad_sentence_index()),
            json.dumps(_bundle_bad_sentence_index()),
        ]
    )

    result = _run(synth, query_id="excerpt-repair-3")

    assert completions.calls == 2
    assert result["claim_analysis_status"] == "FAILED"
    assert result["claims"] == []
    assert result["text"] == "A validated combined answer."


def test_13_unrelated_diagnostic_code_gets_no_sentence_index_instruction():
    synth, completions = _synthesizer(
        [
            json.dumps(_bundle_missing_provider_position()),
            json.dumps(_valid_bundle()),
        ]
    )

    result = _run(synth, query_id="excerpt-repair-4")

    assert completions.calls == 2
    repair_system = _repair_system_content(completions)
    assert "Replace each invalid sentence_index" not in repair_system
    assert repair_system == (
        "Repair the JSON so it exactly matches the supplied schema. Do "
        "not add facts, source names, citation IDs or URLs. Every "
        "support/dispute sentence_index must be the index of an "
        "existing sentence for the matching provider in "
        "provider_responses. Return JSON only."
    )
    assert result["claim_analysis_status"] == "SUCCESS"
