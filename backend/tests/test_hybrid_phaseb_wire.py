"""Tests for the Hybrid Minimal Semantic Wire (perf/synthesizer-hybrid-
phaseb-wire, "LLM judges; backend structures").

claim_matrix, claim_agreements and claim_disagreements are no longer
LLM-authored full structures. The LLM supplies only a minimal per-claim
judgment (importance, referee_assessment, evidence_limitations,
partially_supported_by, provider_judgments) plus optional grouping/
strength/disagreement_type/impact_on_verdict/referee_resolution overrides
(claim_agreements_semantic/claim_disagreements_semantic), and
_build_hybrid_phase_b_sections deterministically reconstructs all three
public structures from claim_analysis + that judgment.

This file covers the scenarios not already exercised by
test_synthesizer_wire_phaseb_step1.py (basic unanimous/derivation/
exclusive_contributions/decisive_factors/repair/salvage/Mongo round-trip):
partial support, provider-attribution failures, every disagreement_type/
impact_on_verdict/strength value, mixed positions, uncertain positions,
FAILED-provider exclusion through the full pipeline, invalid-enum repair,
unknown claim_id grouping, multi-claim grouping, determinism, matrix
completeness, and diagnostic log safety.
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

from providers.conclusion_schema import TrustedConclusionV2  # noqa: E402
from providers.synthesizer import (  # noqa: E402
    ClaimAnalysisWireV1,
    Synthesizer,
    TraceableClaimWire,
    _build_hybrid_phase_b_sections,
    _repair_diagnostic_instruction,
    _resolve_claim_analysis_wire,
)
from providers.traceability_schema import validate_claim_analysis  # noqa: E402


PROVIDERS_TEXT = {
    "openai": "Openai statement.",
    "gemini": "Gemini statement.",
    "mistral": "Mistral statement.",
}


def _answer(provider, status="LIVE"):
    return {
        "id": provider,
        "provider_key": provider,
        "provider_response_id": provider,
        "label": provider,
        "provider": provider,
        "provider_status": status,
        "text": PROVIDERS_TEXT[provider],
    }


def _sentences_by_provider(providers):
    return {provider: [PROVIDERS_TEXT[provider]] for provider in providers}


def wire_support(provider):
    return {"provider": provider, "sentence_index": 0, "provider_response_id": provider}


def wire_judgment(
    providers,
    *,
    importance="medium",
    referee_assessment="Assessment for testing.",
    partially_supported_by=None,
    evidence_limitations=None,
    summaries=None,
):
    summaries = summaries or {}
    return {
        "importance": importance,
        "referee_assessment": referee_assessment,
        "evidence_limitations": evidence_limitations or [],
        "partially_supported_by": partially_supported_by or [],
        "provider_judgments": [
            {
                "provider": provider,
                "summary": summaries.get(provider, f"{provider} summary."),
            }
            for provider in providers
        ],
    }


def wire_claim(
    claim_id,
    *,
    originating,
    supporting,
    disputing=None,
    status="supported",
    reason="Test reason.",
    judgment_kwargs=None,
):
    disputing = disputing or []
    support_items = [wire_support(p) for p in supporting]
    dispute_items = [wire_support(p) for p in disputing]
    judgment_kwargs = dict(judgment_kwargs or {})
    judgment_kwargs.setdefault("importance", "medium")
    return {
        "id": claim_id,
        "text": f"Claim text for {claim_id}.",
        "claim_type": "fact",
        "originating_models": originating,
        "supporting_models": supporting,
        "disputing_models": disputing,
        "support": support_items,
        "dispute": dispute_items,
        "citation_ids": [],
        "assessment": {"status": status, "reason": reason},
        "judgment": wire_judgment(originating, **judgment_kwargs),
    }


def _minimal_conclusion(**overrides):
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
    return TrustedConclusionV2.model_validate(payload)


def build_sections(
    claims,
    *,
    agreements_semantic=None,
    disagreements_semantic=None,
    providers=("openai", "gemini", "mistral"),
):
    wire = ClaimAnalysisWireV1.model_validate(
        {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": claims,
            "claim_agreements_semantic": agreements_semantic or [],
            "claim_disagreements_semantic": disagreements_semantic or [],
        }
    )
    answers = [_answer(p) for p in providers]
    resolved, judgments = _resolve_claim_analysis_wire(
        wire, _sentences_by_provider(providers)
    )
    analysis = validate_claim_analysis(resolved, answers, [], "LIVE")
    conclusion = _minimal_conclusion()
    return _build_hybrid_phase_b_sections(
        conclusion,
        analysis,
        answers,
        judgments,
        wire.claim_agreements_semantic,
        wire.claim_disagreements_semantic,
    )


# --- A: unanimous claim ------------------------------------------------


def test_a_unanimous_claim_derives_correct_agreement_level():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini", "mistral"],
            supporting=["openai", "gemini", "mistral"],
        )
    ]
    sections = build_sections(claims)
    assert sections["claim_matrix"][0]["agreement_level"] == "unanimous"


# --- B: partially_supports override -------------------------------------


def test_b_partially_supported_by_downgrades_position():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai", "gemini"],
            judgment_kwargs={"partially_supported_by": ["gemini"]},
        )
    ]
    sections = build_sections(claims, providers=("openai", "gemini"))
    positions = {
        p["provider"]: p["position"]
        for p in sections["claim_matrix"][0]["provider_positions"]
    }
    assert positions["openai"] == "supports"
    assert positions["gemini"] == "partially_supports"


# --- C: partially_supported_by with an invalid provider fails -----------


def test_c_partially_supported_by_provider_not_a_supporter_fails():
    claim = wire_claim(
        "claim_1",
        originating=["openai", "gemini"],
        supporting=["openai"],
        disputing=["gemini"],
        status="disputed",
        judgment_kwargs={"partially_supported_by": ["gemini"]},
    )
    with pytest.raises(
        ValidationError, match="partially_supported_by requires a supporting provider"
    ):
        TraceableClaimWire.model_validate(claim)


def test_c_provider_judgments_must_cover_originating_models_exactly():
    claim = wire_claim(
        "claim_1",
        originating=["openai", "gemini"],
        supporting=["openai", "gemini"],
    )
    # Drop gemini's judgment entry: no longer exactly covers originating.
    claim["judgment"]["provider_judgments"] = [
        item
        for item in claim["judgment"]["provider_judgments"]
        if item["provider"] != "gemini"
    ]
    with pytest.raises(
        ValidationError,
        match="provider judgments must exactly cover originating_models",
    ):
        TraceableClaimWire.model_validate(claim)


# --- D-I: every disagreement_type value ----------------------------------


@pytest.mark.parametrize(
    "disagreement_type",
    ["factual", "interpretation", "degree", "timeframe", "uncertainty", "emphasis"],
)
def test_d_to_i_every_disagreement_type_is_preserved(disagreement_type):
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        )
    ]
    sections = build_sections(
        claims,
        disagreements_semantic=[
            {
                "claim_ids": ["claim_1"],
                "disagreement_type": disagreement_type,
                "impact_on_verdict": "medium",
                "referee_resolution": "How the verdict resolves this.",
            }
        ],
        providers=("openai", "gemini"),
    )
    assert len(sections["claim_disagreements"]) == 1
    assert sections["claim_disagreements"][0]["disagreement_type"] == (
        disagreement_type
    )
    # Never silently defaults to "interpretation" when a different value
    # was explicitly supplied.
    if disagreement_type != "interpretation":
        assert sections["claim_disagreements"][0]["disagreement_type"] != (
            "interpretation"
        )


# --- J-M: every impact_on_verdict value -----------------------------------


@pytest.mark.parametrize("impact", ["high", "medium", "low", "none"])
def test_j_to_m_every_impact_on_verdict_value_is_preserved(impact):
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        )
    ]
    sections = build_sections(
        claims,
        disagreements_semantic=[
            {
                "claim_ids": ["claim_1"],
                "disagreement_type": "factual",
                "impact_on_verdict": impact,
                "referee_resolution": "How the verdict resolves this.",
            }
        ],
        providers=("openai", "gemini"),
    )
    assert sections["claim_disagreements"][0]["impact_on_verdict"] == impact


# --- N: every agreement strength value -------------------------------------


@pytest.mark.parametrize("strength", ["high", "medium", "low"])
def test_n_every_agreement_strength_value_is_preserved(strength):
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai", "gemini"],
        )
    ]
    sections = build_sections(
        claims,
        agreements_semantic=[{"claim_ids": ["claim_1"], "strength": strength}],
        providers=("openai", "gemini"),
    )
    assert sections["claim_agreements"][0]["strength"] == strength


# --- O: mixed provider positions in one claim -----------------------------


def test_o_mixed_provider_positions_supports_contradicts_not_mentioned():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        )
    ]
    sections = build_sections(claims, providers=("openai", "gemini", "mistral"))
    positions = {
        p["provider"]: p["position"]
        for p in sections["claim_matrix"][0]["provider_positions"]
    }
    assert positions == {
        "openai": "supports",
        "gemini": "contradicts",
        "mistral": "not_mentioned",
    }
    assert sections["claim_matrix"][0]["agreement_level"] == "disputed"


# --- P: FAILED provider excluded through the full hybrid pipeline --------


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


def _run(synth, answers, *, query_id):
    return asyncio.run(
        synth.synthesize(
            "Does caching help?",
            answers,
            "en",
            correlation_id=query_id,
        )
    )


def _bundle_single_provider_claim():
    claim = wire_claim(
        "claim_1",
        originating=["openai"],
        supporting=["openai"],
    )
    return {
        "trusted_conclusion": {
            "schema_version": "2.0",
            "final_answer": "A validated combined answer.",
            "agreements": [],
            "disagreements": [],
            "strongest_evidence": [],
            "remaining_uncertainties": [],
            "unsupported_claims": [],
            "confidence": {
                "level": "low",
                "reason": "Only one provider addressed this point.",
                "factors": {
                    "model_agreement": "low",
                    "evidence_quality": "medium",
                    "uncertainty": "high",
                },
            },
            "referee_reasoning": "The panel provides partial coverage.",
            "what_could_change_the_verdict": [],
        },
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [claim],
        },
    }


def test_p_failed_provider_never_enters_the_derived_claim_matrix():
    bundle = _bundle_single_provider_claim()
    synth, completions = _synthesizer([json.dumps(bundle)])
    answers = [
        {
            "id": "openai",
            "provider_key": "openai",
            "provider_response_id": "openai",
            "label": "openai",
            "provider": "openai",
            "provider_status": "LIVE",
            "text": PROVIDERS_TEXT["openai"],
        },
        {
            "id": "gemini",
            "provider_key": "gemini",
            "provider_response_id": "gemini",
            "label": "gemini",
            "provider": "gemini",
            "provider_status": "FAILED",
            "text": "",
        },
    ]
    result = _run(synth, answers, query_id="failed-provider")

    assert result["claim_analysis_status"] == "SUCCESS"
    matrix = result["structured_conclusion"]["claim_matrix"]
    assert len(matrix) == 1
    providers_in_matrix = {
        p["provider"] for p in matrix[0]["provider_positions"]
    }
    assert providers_in_matrix == {"openai"}
    assert "gemini" not in providers_in_matrix


# --- Q: not_mentioned provider gets an empty deterministic summary --------


def test_q_not_mentioned_provider_gets_empty_summary_no_llm_call():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai"],
            supporting=["openai"],
        )
    ]
    sections = build_sections(claims, providers=("openai", "gemini"))
    positions = {
        p["provider"]: p for p in sections["claim_matrix"][0]["provider_positions"]
    }
    assert positions["gemini"]["position"] == "not_mentioned"
    assert positions["gemini"]["summary"] == ""


# --- R: uncertain provider (originates but neither supports nor disputes) -


def test_r_provider_originating_without_support_or_dispute_is_uncertain():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=[],
            judgment_kwargs={
                "summaries": {
                    "openai": "OpenAI clearly supports it.",
                    "gemini": "Gemini mentions it without taking a side.",
                }
            },
        )
    ]
    sections = build_sections(claims, providers=("openai", "gemini"))
    positions = {
        p["provider"]: p["position"]
        for p in sections["claim_matrix"][0]["provider_positions"]
    }
    assert positions == {"openai": "supports", "gemini": "uncertain"}


# --- V: invalid semantic enum gets a targeted repair instruction ---------


def test_v_invalid_importance_enum_gets_targeted_repair_instruction():
    claim = wire_claim(
        "claim_1", originating=["openai"], supporting=["openai"]
    )
    payload = {
        "schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": [claim],
    }
    payload["claims"][0]["judgment"]["importance"] = "critical"
    with pytest.raises(ValidationError) as caught:
        ClaimAnalysisWireV1.model_validate(payload)
    instruction = _repair_diagnostic_instruction(caught.value)
    assert "judgment.importance must be exactly one of" in instruction


def test_v_invalid_disagreement_type_enum_gets_targeted_repair_instruction():
    payload = {
        "schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": [],
        "claim_disagreements_semantic": [
            {
                "claim_ids": ["claim_1"],
                "disagreement_type": "nonsense",
                "impact_on_verdict": "medium",
                "referee_resolution": "Resolution text.",
            }
        ],
    }
    with pytest.raises(ValidationError) as caught:
        ClaimAnalysisWireV1.model_validate(payload)
    instruction = _repair_diagnostic_instruction(caught.value)
    assert "disagreement_type must be exactly one of" in instruction


def test_v_invalid_impact_on_verdict_enum_gets_targeted_repair_instruction():
    payload = {
        "schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": [],
        "claim_disagreements_semantic": [
            {
                "claim_ids": ["claim_1"],
                "disagreement_type": "factual",
                "impact_on_verdict": "critical",
                "referee_resolution": "Resolution text.",
            }
        ],
    }
    with pytest.raises(ValidationError) as caught:
        ClaimAnalysisWireV1.model_validate(payload)
    instruction = _repair_diagnostic_instruction(caught.value)
    assert "impact_on_verdict must be exactly one of" in instruction


def test_v_invalid_strength_enum_gets_targeted_repair_instruction():
    payload = {
        "schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": [],
        "claim_agreements_semantic": [
            {"claim_ids": ["claim_1"], "strength": "extreme"}
        ],
    }
    with pytest.raises(ValidationError) as caught:
        ClaimAnalysisWireV1.model_validate(payload)
    instruction = _repair_diagnostic_instruction(caught.value)
    assert "strength must be exactly one of" in instruction


# --- W: unknown claim_id in semantic grouping fails ------------------------


def test_w_unknown_claim_id_in_agreements_semantic_fails():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai", "gemini"],
        )
    ]
    with pytest.raises(
        ValueError, match="claim semantic override references unknown claim IDs"
    ):
        build_sections(
            claims,
            agreements_semantic=[{"claim_ids": ["claim_ghost"], "strength": "high"}],
            providers=("openai", "gemini"),
        )


def test_w_unknown_claim_id_in_disagreements_semantic_fails():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        )
    ]
    with pytest.raises(
        ValueError, match="claim semantic override references unknown claim IDs"
    ):
        build_sections(
            claims,
            disagreements_semantic=[
                {
                    "claim_ids": ["claim_ghost"],
                    "disagreement_type": "factual",
                    "impact_on_verdict": "medium",
                    "referee_resolution": "Resolution text.",
                }
            ],
            providers=("openai", "gemini"),
        )


# --- X/Y: default 1 claim = 1 agreement/disagreement -----------------------


def test_x_default_grouping_is_one_claim_per_agreement():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai", "gemini"],
        ),
        wire_claim(
            "claim_2",
            originating=["openai", "gemini"],
            supporting=["openai", "gemini"],
        ),
    ]
    sections = build_sections(
        claims,
        agreements_semantic=[
            {"claim_ids": ["claim_1"], "strength": "high"},
            {"claim_ids": ["claim_2"], "strength": "medium"},
        ],
        providers=("openai", "gemini"),
    )
    assert len(sections["claim_agreements"]) == 2
    assert {tuple(item["claim_ids"]) for item in sections["claim_agreements"]} == {
        ("claim_1",),
        ("claim_2",),
    }


def test_y_default_grouping_is_one_claim_per_disagreement():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        ),
        wire_claim(
            "claim_2",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        ),
    ]
    sections = build_sections(
        claims,
        disagreements_semantic=[
            {
                "claim_ids": ["claim_1"],
                "disagreement_type": "factual",
                "impact_on_verdict": "medium",
                "referee_resolution": "Resolution for claim 1.",
            },
            {
                "claim_ids": ["claim_2"],
                "disagreement_type": "degree",
                "impact_on_verdict": "low",
                "referee_resolution": "Resolution for claim 2.",
            },
        ],
        providers=("openai", "gemini"),
    )
    assert len(sections["claim_disagreements"]) == 2


# --- Z/AA: multi-claim grouping overrides ----------------------------------


def test_z_multi_claim_agreement_override_groups_claims():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai", "gemini"],
        ),
        wire_claim(
            "claim_2",
            originating=["openai", "gemini"],
            supporting=["openai", "gemini"],
        ),
    ]
    sections = build_sections(
        claims,
        agreements_semantic=[
            {"claim_ids": ["claim_1", "claim_2"], "strength": "high"}
        ],
        providers=("openai", "gemini"),
    )
    assert len(sections["claim_agreements"]) == 1
    assert sections["claim_agreements"][0]["claim_ids"] == ["claim_1", "claim_2"]
    assert set(sections["claim_agreements"][0]["providers"]) == {"openai", "gemini"}


def test_aa_multi_claim_disagreement_override_groups_claims():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        ),
        wire_claim(
            "claim_2",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        ),
    ]
    sections = build_sections(
        claims,
        disagreements_semantic=[
            {
                "claim_ids": ["claim_1", "claim_2"],
                "disagreement_type": "degree",
                "impact_on_verdict": "high",
                "referee_resolution": "Shared resolution across both claims.",
            }
        ],
        providers=("openai", "gemini"),
    )
    assert len(sections["claim_disagreements"]) == 1
    assert sections["claim_disagreements"][0]["claim_ids"] == ["claim_1", "claim_2"]


# --- AB: deterministic repeatability (hybrid path) --------------------------


def test_ab_hybrid_derivation_is_deterministic_given_same_inputs():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        )
    ]
    kwargs = dict(
        disagreements_semantic=[
            {
                "claim_ids": ["claim_1"],
                "disagreement_type": "degree",
                "impact_on_verdict": "medium",
                "referee_resolution": "Resolution text.",
            }
        ],
        providers=("openai", "gemini"),
    )
    first = build_sections(claims, **kwargs)
    second = build_sections(claims, **kwargs)
    assert first == second


# --- AC/AD/AE: matrix completeness and structural coherence ---------------


def test_ac_claim_matrix_lists_every_participating_provider():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai"],
            supporting=["openai"],
        )
    ]
    sections = build_sections(claims, providers=("openai", "gemini", "mistral"))
    providers_in_matrix = {
        p["provider"] for p in sections["claim_matrix"][0]["provider_positions"]
    }
    assert providers_in_matrix == {"openai", "gemini", "mistral"}


def test_ad_agreement_providers_are_always_a_subset_of_eligible_positions():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini", "mistral"],
            supporting=["openai", "gemini"],
        )
    ]
    sections = build_sections(
        claims,
        agreements_semantic=[{"claim_ids": ["claim_1"], "strength": "high"}],
    )
    matrix_positions = {
        p["provider"]: p["position"]
        for p in sections["claim_matrix"][0]["provider_positions"]
    }
    eligible = {
        provider
        for provider, position in matrix_positions.items()
        if position in ("supports", "partially_supports")
    }
    assert set(sections["claim_agreements"][0]["providers"]).issubset(eligible)


def test_ae_disagreement_positions_are_always_consistent_with_matrix():
    claims = [
        wire_claim(
            "claim_1",
            originating=["openai", "gemini", "mistral"],
            supporting=["openai"],
            disputing=["gemini"],
            status="disputed",
        )
    ]
    sections = build_sections(
        claims,
        disagreements_semantic=[
            {
                "claim_ids": ["claim_1"],
                "disagreement_type": "factual",
                "impact_on_verdict": "medium",
                "referee_resolution": "Resolution text.",
            }
        ],
    )
    matrix_positions = {
        p["provider"]: p["position"]
        for p in sections["claim_matrix"][0]["provider_positions"]
    }
    position_values = set(matrix_positions.values())
    assert "contradicts" in position_values
    assert bool(position_values & {"supports", "partially_supports"})
    disagreement_providers = {
        item["provider"] for item in sections["claim_disagreements"][0]["positions"]
    }
    assert disagreement_providers.issubset(set(matrix_positions))


# --- AK: no prompt/response/judgment content leaks into diagnostic logs ---


def test_ak_semantic_override_diagnostics_do_not_leak_judgment_content(caplog):
    secret = "SECRET_JUDGMENT_TEXT_MUST_NOT_LEAK"
    claim = wire_claim(
        "claim_1",
        originating=["openai"],
        supporting=["openai"],
        judgment_kwargs={"referee_assessment": secret},
    )
    bundle = {
        "trusted_conclusion": {
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
        },
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [claim],
            "claim_agreements_semantic": [
                {"claim_ids": ["claim_ghost"], "strength": "high"}
            ],
        },
    }
    synth, completions = _synthesizer(
        [json.dumps(bundle), json.dumps(bundle)]
    )
    answers = [_answer("openai")]
    with caplog.at_level(logging.WARNING):
        with pytest.raises(Exception):
            _run(synth, answers, query_id="leak-check")
    assert secret not in caplog.text
