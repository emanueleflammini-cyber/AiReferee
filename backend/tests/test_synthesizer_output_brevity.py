"""Tests for the claim-count and output-brevity prompt fix.

Addresses the real production latency trace (query_id
8cb17e10-ea46-4ea0-b354-cbcec326d894: SUCCESS on the first attempt,
25829ms initial call, 4989 output tokens): this is a prompt-only patch
(no schema, validator, Structured Outputs, model, timeout/retry, Early
Synthesis, quorum/Jaccard, excerpt-rule, or Phase B derivation change),
targeting decisive-claim count and duplicated free-text narration
identified in the read-only latency audit (claim_matrix[].referee_
assessment and provider_positions[].summary restating claim_analysis.
claims[].assessment.reason).
"""
from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import eligible_synthesis_answers  # noqa: E402
from providers.synthesizer import SynthesisBundleV3, _system_prompt  # noqa: E402


def behavior_prompt(provider_labels: dict[str, str] | None = None) -> str:
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


# --- claim count -----------------------------------------------------------


def test_prompt_targets_three_to_five_decisive_claims():
    prompt = behavior_prompt()
    assert (
        "Build claim_matrix from those decisive claims: target 3 to 5 "
        "items"
    ) in prompt
    assert "materially decide the verdict" in prompt
    assert "never split a single point into trivial sub-claims" in prompt


def test_prompt_favors_three_claims_for_simple_questions():
    prompt = behavior_prompt()
    assert (
        "Use 3 for a simple, narrowly-scoped question with few "
        "genuinely distinct decisive points"
    ) in prompt
    assert (
        "Go to 4 or 5 only when the question has that many materially "
        "distinct decisive points"
    ) in prompt


def test_five_is_a_generation_target_not_a_hard_cap():
    prompt = behavior_prompt()
    assert (
        "Exceed 5 only if the supplied evidence genuinely contains more "
        "decisive points than that"
    ) in prompt
    assert "do not pad claim_matrix to reach a target count" in prompt
    # No structural schema limit was introduced: claim_matrix stays an
    # unbounded list (default_factory=list, no max_length) exactly as
    # before this patch.
    schema = SynthesisBundleV3.model_json_schema()
    claim_matrix_schema = schema["$defs"]["TrustedConclusionV2"][
        "properties"
    ]["claim_matrix"]
    assert "maxItems" not in claim_matrix_schema


def test_old_3_to_8_wording_is_gone():
    prompt = behavior_prompt()
    assert "3 to 8" not in prompt


# --- brevity / anti-redundancy ---------------------------------------------


def test_prompt_states_general_conciseness_and_non_redundancy():
    prompt = behavior_prompt()
    assert "Be concise and non-redundant across the whole response" in prompt
    assert (
        "Do not restate information already encoded in structured fields"
    ) in prompt


def test_referee_assessment_must_be_concise():
    prompt = behavior_prompt()
    assert (
        "claim_matrix[].referee_assessment and Disagreement."
        "referee_assessment must be concise"
    ) in prompt
    assert "not a restated narrative" in prompt


def test_provider_position_summary_must_not_repeat_assessment_reason():
    prompt = behavior_prompt()
    assert (
        "claim_matrix[].provider_positions[].summary must not repeat the "
        "wording of that same claim's claim_analysis.claims[].assessment."
        "reason"
    ) in prompt


def test_agreements_and_disagreements_must_not_duplicate_each_other():
    prompt = behavior_prompt()
    assert "agreements and disagreements must not restate each other" in prompt
    assert (
        "must not repeat claim-level detail already captured in "
        "claim_matrix"
    ) in prompt


def test_strongest_evidence_non_duplication_instruction_still_present():
    prompt = behavior_prompt()
    assert (
        "strongest_evidence must add evidentiary context, not repeat the "
        "same wording already used in agreements"
    ) in prompt


def test_final_answer_is_explicitly_exempt_from_brevity_and_stays_complete():
    prompt = behavior_prompt()
    assert (
        "This conciseness requirement never applies to final_answer"
    ) in prompt
    assert (
        "final_answer must stay complete, specific and readable -- never "
        "shorten it into a telegraphic or incomplete answer"
    ) in prompt
    # The original final_answer completeness rules are untouched.
    assert "final_answer must directly and fully answer the question" in prompt


def test_excerpts_are_explicitly_exempt_from_brevity():
    prompt = behavior_prompt()
    assert (
        "This conciseness requirement never shortens support[]/dispute[] "
        "response_excerpt"
    ) in prompt


# --- regression: previous prompt patches remain intact ---------------------


def test_exact_excerpt_rules_from_previous_patch_are_unchanged():
    prompt = behavior_prompt()
    assert (
        "a short, CONTIGUOUS, character-for-character substring copied "
        "directly from that provider's response field above"
    ) in prompt
    assert "Never: translate it" in prompt
    assert (
        "This translation requirement does NOT apply to "
        "support[].response_excerpt"
    ) in prompt


def test_disagreement_claim_disagreement_path_split_from_previous_patch_is_unchanged():
    prompt = behavior_prompt()
    assert (
        "trusted_conclusion.disagreements[] and trusted_conclusion."
        "claim_disagreements[] are two different structures"
    ) in prompt
    assert "positions[] uses the field 'model' (never 'provider')" in prompt
    assert "positions[] uses the field 'provider' (never 'model')" in prompt


def test_traceable_claim_invariants_from_previous_patch_are_unchanged():
    prompt = behavior_prompt()
    assert (
        "a provider can never appear in both supporting_models and "
        "disputing_models for the same claim"
    ) in prompt


def test_failed_provider_participant_exclusion_is_unchanged():
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
    ]
    eligible = eligible_synthesis_answers(responses, "LIVE")
    labels = {answer["provider_key"]: answer["label"] for answer in eligible}
    prompt = behavior_prompt(labels)
    assert list(labels) == ["openai"]
    assert "Gemini" not in prompt
    assert "FAILED providers are absent" in prompt
