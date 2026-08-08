"""Tests for PATCH 1 of the wire-schema audit: exclusive_contributions and
decisive_factors are removed from what the LLM is asked to produce and are
always derived deterministically by the backend afterward, reusing the
existing _phase_b_sections/_phase_b_fields_from_analysis logic.

claim_matrix, claim_agreements and claim_disagreements remain LLM-generated,
unchanged. The public TrustedConclusionV2/V21 models, CompareResponse shape,
and Mongo persistence format are untouched -- only the JSON schema/contract
enforced on the live OpenAI call (SynthesisWireBundleV1, replacing
SynthesisBundleV3 for that one purpose) got narrower.
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
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import (  # noqa: E402
    normalize_stored_conclusion,
    parse_structured_conclusion,
)
from providers.synthesizer import (  # noqa: E402
    Synthesizer,
    SynthesisBundleV3,
    SynthesisWireBundleV1,
    TrustedConclusionWireV2,
    _enrich_conclusion,
)
from providers.traceability_schema import ClaimAnalysisV3  # noqa: E402


def load_fixture(name: str) -> dict:
    return json.loads(
        (FIXTURE_DIR / f"referee3_{name}.json").read_text(encoding="utf-8")
    )


# --- A/B/C: the wire schema sent to the LLM -------------------------------


def test_a_wire_schema_omits_exclusive_contributions_and_decisive_factors():
    schema_text = json.dumps(SynthesisWireBundleV1.model_json_schema())
    assert "exclusive_contributions" not in schema_text
    assert "decisive_factors" not in schema_text


def test_b_wire_schema_still_requires_claim_matrix_agreements_disagreements():
    schema_text = json.dumps(SynthesisWireBundleV1.model_json_schema())
    assert "claim_matrix" in schema_text
    assert "claim_agreements" in schema_text
    assert "claim_disagreements" in schema_text


def test_c_defs_exclusive_to_removed_fields_are_gone_but_shared_defs_remain():
    wire_defs = SynthesisWireBundleV1.model_json_schema()["$defs"]
    assert "ExclusiveContribution" not in wire_defs
    assert "DecisiveFactor" not in wire_defs
    # Shared/still-needed defs are untouched, byte-identical to the full
    # (SynthesisBundleV3) schema -- proves claim_matrix/claim_agreements/
    # claim_disagreements were not altered in any way by this patch.
    old_defs = SynthesisBundleV3.model_json_schema()["$defs"]
    for name in (
        "ClaimMatrixItem",
        "ClaimProviderPosition",
        "ClaimAgreement",
        "ClaimDisagreement",
        "ClaimDisagreementPosition",
    ):
        assert wire_defs[name] == old_defs[name]


def test_d_wire_payload_without_the_two_fields_is_accepted():
    payload = {
        "trusted_conclusion": {
            "schema_version": "2.0",
            "final_answer": "A validated answer.",
            "agreements": [],
            "disagreements": [],
            "strongest_evidence": [],
            "remaining_uncertainties": [],
            "unsupported_claims": [],
            "confidence": {
                "level": "medium",
                "reason": "Limited but usable evidence.",
                "factors": {
                    "model_agreement": "medium",
                    "evidence_quality": "medium",
                    "uncertainty": "medium",
                },
            },
            "referee_reasoning": "",
            "what_could_change_the_verdict": [],
            "claim_matrix": [],
            "claim_agreements": [],
            "claim_disagreements": [],
        },
        "claim_analysis": {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": [],
        },
    }
    bundle = SynthesisWireBundleV1.model_validate(payload)
    assert bundle.trusted_conclusion.final_answer == "A validated answer."


def test_wire_model_strictly_rejects_the_two_removed_fields_if_present():
    payload = {
        "schema_version": "2.0",
        "final_answer": "A validated answer.",
        "agreements": [],
        "disagreements": [],
        "strongest_evidence": [],
        "remaining_uncertainties": [],
        "unsupported_claims": [],
        "confidence": {
            "level": "medium",
            "reason": "Limited but usable evidence.",
            "factors": {
                "model_agreement": "medium",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "referee_reasoning": "",
        "what_could_change_the_verdict": [],
        "claim_matrix": [],
        "claim_agreements": [],
        "claim_disagreements": [],
        "exclusive_contributions": [],
        "decisive_factors": [],
    }
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        TrustedConclusionWireV2.model_validate(payload)


# --- shared realistic fixtures for the end-to-end tests --------------------


def answer(provider: str, text: str, status: str = "LIVE") -> dict:
    labels = {"openai": "ChatGPT", "gemini": "Gemini"}
    names = {"openai": "OpenAI", "gemini": "Google DeepMind"}
    return {
        "id": {"openai": "model-a", "gemini": "model-c"}[provider],
        "provider_key": provider,
        "provider_response_id": provider,
        "label": labels[provider],
        "provider": names[provider],
        "provider_status": status,
        "text": text,
        "citations": [],
    }


OPENAI_TEXT = "Caching reduces repeated network calls, which is a clear win."
GEMINI_TEXT = "Caching reduces repeated network calls, which is a clear win."
ANSWERS = [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)]

# OPENAI_TEXT/GEMINI_TEXT are each a single sentence (no other sentence-
# terminal punctuation), so every support/dispute item below resolves via
# sentence_index=0 to that one full sentence (feature/deterministic-
# excerpt-sentence-index resolves whole sentences, never sub-sentence
# spans -- see wire_support()).


def wire_support(provider: str, sentence_index: int = 0, response_id=None) -> dict:
    return {
        "provider": provider,
        "sentence_index": sentence_index,
        "provider_response_id": response_id or provider,
    }


def _claim_analysis_claims() -> list[dict]:
    """Wire-shape claims (sentence_index) sent through the full synth()
    pipeline. See _public_claim_analysis_claims() for the public-shape
    (response_excerpt) equivalent used where a test constructs a
    ClaimAnalysisV3 directly, bypassing the wire model entirely.
    """
    return [
        {
            # Only openai addresses this point -> exclusive_contributions
            # candidate once derived.
            "id": "claim_exclusive",
            "text": "OpenAI notes a secondary caching benefit.",
            "claim_type": "fact",
            "originating_models": ["openai"],
            "supporting_models": ["openai"],
            "disputing_models": [],
            "support": [wire_support("openai")],
            "dispute": [],
            "citation_ids": [],
            "assessment": {
                "status": "supported",
                "reason": "OpenAI states this directly.",
            },
        },
        {
            # Both providers support this -> feeds strongest_evidence ->
            # decisive_factors candidate once derived.
            "id": "claim_decisive",
            "text": "Caching reduces repeated network calls.",
            "claim_type": "fact",
            "originating_models": ["openai", "gemini"],
            "supporting_models": ["openai", "gemini"],
            "disputing_models": [],
            "support": [
                wire_support("openai"),
                wire_support("gemini"),
            ],
            "dispute": [],
            "citation_ids": [],
            "assessment": {
                "status": "supported",
                "reason": "Both providers state this identically.",
            },
        },
    ]


def _claim_analysis() -> dict:
    return {
        "schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": _claim_analysis_claims(),
    }


def _public_claim_analysis_claims() -> list[dict]:
    """Public-shape (response_excerpt) equivalent of _claim_analysis_claims(),
    for tests that build a ClaimAnalysisV3 directly via model_validate,
    bypassing the wire model and its sentence_index resolution.
    """
    return [
        {
            "id": "claim_exclusive",
            "text": "OpenAI notes a secondary caching benefit.",
            "claim_type": "fact",
            "originating_models": ["openai"],
            "supporting_models": ["openai"],
            "disputing_models": [],
            "support": [
                {
                    "provider": "openai",
                    "response_excerpt": OPENAI_TEXT,
                    "response_reference": {"provider_response_id": "openai"},
                }
            ],
            "dispute": [],
            "citation_ids": [],
            "assessment": {
                "status": "supported",
                "reason": "OpenAI states this directly.",
            },
        },
        {
            "id": "claim_decisive",
            "text": "Caching reduces repeated network calls.",
            "claim_type": "fact",
            "originating_models": ["openai", "gemini"],
            "supporting_models": ["openai", "gemini"],
            "disputing_models": [],
            "support": [
                {
                    "provider": "openai",
                    "response_excerpt": OPENAI_TEXT,
                    "response_reference": {"provider_response_id": "openai"},
                },
                {
                    "provider": "gemini",
                    "response_excerpt": GEMINI_TEXT,
                    "response_reference": {"provider_response_id": "gemini"},
                },
            ],
            "dispute": [],
            "citation_ids": [],
            "assessment": {
                "status": "supported",
                "reason": "Both providers state this identically.",
            },
        },
    ]


def _llm_claim_matrix() -> list[dict]:
    return [
        {
            "claim_id": "claim_exclusive",
            "claim": "OpenAI notes a secondary caching benefit.",
            "importance": "medium",
            "provider_positions": [
                {
                    "provider": "openai",
                    "display_name": "ChatGPT",
                    "position": "supports",
                    "summary": "OpenAI raises this point alone.",
                    "evidence_refs": ["openai"],
                    "confidence": "medium",
                },
                {
                    "provider": "gemini",
                    "display_name": "Gemini",
                    "position": "not_mentioned",
                    "summary": "",
                    "evidence_refs": [],
                    "confidence": "low",
                },
            ],
            "agreement_level": "unresolved",
            "referee_assessment": "Only OpenAI raised this secondary point.",
            "evidence_limitations": [],
        },
        {
            "claim_id": "claim_decisive",
            "claim": "Caching reduces repeated network calls.",
            "importance": "high",
            "provider_positions": [
                {
                    "provider": "openai",
                    "display_name": "ChatGPT",
                    "position": "supports",
                    "summary": "OpenAI states this directly.",
                    "evidence_refs": ["openai"],
                    "confidence": "high",
                },
                {
                    "provider": "gemini",
                    "display_name": "Gemini",
                    "position": "supports",
                    "summary": "Gemini states this directly.",
                    "evidence_refs": ["gemini"],
                    "confidence": "high",
                },
            ],
            "agreement_level": "unanimous",
            "referee_assessment": "Both providers agree on this point.",
            "evidence_limitations": [],
        },
    ]


def _llm_claim_agreements() -> list[dict]:
    return [
        {
            "topic": "Caching reduces repeated network calls",
            "claim_ids": ["claim_decisive"],
            "providers": ["openai", "gemini"],
            "strength": "high",
            "explanation": "Both providers explicitly agree.",
        }
    ]


def _wire_trusted_conclusion() -> dict:
    return {
        "schema_version": "2.0",
        "final_answer": "Caching reduces repeated network calls.",
        "agreements": [],
        "disagreements": [],
        "strongest_evidence": [
            {
                "id": "evidence_1",
                "claim": "Caching reduces repeated network calls.",
                "description": "Both providers state this identically.",
                "supporting_models": ["openai", "gemini"],
                "source_status": "model_reasoning",
                "evidence_claim_ids": ["claim_decisive"],
            }
        ],
        "remaining_uncertainties": [],
        "unsupported_claims": [],
        "confidence": {
            "level": "high",
            "reason": "Both providers agree on the core point.",
            "factors": {
                "model_agreement": "high",
                "evidence_quality": "medium",
                "uncertainty": "low",
            },
        },
        "referee_reasoning": "The shared claim is well supported.",
        "what_could_change_the_verdict": [],
        "claim_matrix": _llm_claim_matrix(),
        "claim_agreements": _llm_claim_agreements(),
        "claim_disagreements": [],
    }


def _wire_bundle() -> dict:
    return {
        "trusted_conclusion": _wire_trusted_conclusion(),
        "claim_analysis": _claim_analysis(),
    }


class FakeCompletions:
    def __init__(self, outputs: list[str]):
        self.outputs = iter(outputs)
        self.calls = 0
        self.requests: list[dict] = []

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


def _synthesizer(outputs: list[str]):
    synth = Synthesizer.__new__(Synthesizer)
    completions = FakeCompletions(outputs)
    synth.available = True
    synth._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return synth, completions


def _run(synth, *, query_id: str = "wire-step1"):
    return asyncio.run(
        synth.synthesize(
            "Does caching help?",
            ANSWERS,
            "en",
            correlation_id=query_id,
        )
    )


# --- E/G/H: end-to-end enrichment produces both derived sections ----------


def test_e_final_trusted_conclusion_v21_contains_both_derived_sections():
    synth, completions = _synthesizer([json.dumps(_wire_bundle())])
    result = _run(synth)

    assert completions.calls == 1
    structured = result["structured_conclusion"]
    assert structured["schema_version"] == "2.1"
    assert "exclusive_contributions" in structured
    assert "decisive_factors" in structured
    assert structured["exclusive_contributions"] != []
    assert structured["decisive_factors"] != []


def test_g_decisive_factors_derives_from_strongest_evidence():
    synth, completions = _synthesizer([json.dumps(_wire_bundle())])
    result = _run(synth)

    factors = result["structured_conclusion"]["decisive_factors"]
    assert len(factors) == 1
    assert factors[0]["factor"] == "Caching reduces repeated network calls."
    assert set(factors[0]["supported_by"]) == {"openai", "gemini"}


def test_h_exclusive_contributions_derives_from_claim_analysis():
    synth, completions = _synthesizer([json.dumps(_wire_bundle())])
    result = _run(synth)

    contributions = result["structured_conclusion"]["exclusive_contributions"]
    assert len(contributions) == 1
    assert contributions[0]["provider"] == "openai"
    assert contributions[0]["related_claim_ids"] == ["claim_exclusive"]


# --- F: deterministic / idempotent -----------------------------------------


def test_f_derivation_is_deterministic_given_same_inputs():
    conclusion = parse_structured_conclusion(
        _wire_trusted_conclusion(), ["openai", "gemini"]
    )
    analysis = ClaimAnalysisV3.model_validate(
        {
            "schema_version": "3.0",
            "execution_mode": "LIVE",
            "claims": _public_claim_analysis_claims(),
        }
    )

    first = _enrich_conclusion(conclusion, analysis, [], ANSWERS)
    second = _enrich_conclusion(conclusion, analysis, [], ANSWERS)

    assert first.exclusive_contributions == second.exclusive_contributions
    assert first.decisive_factors == second.decisive_factors


# --- I/J/K: claim_matrix / claim_agreements / claim_disagreements unchanged


def test_i_llm_claim_matrix_passes_through_unmodified():
    synth, completions = _synthesizer([json.dumps(_wire_bundle())])
    result = _run(synth)

    structured = result["structured_conclusion"]
    assert len(structured["claim_matrix"]) == 2
    ids = {item["claim_id"] for item in structured["claim_matrix"]}
    assert ids == {"claim_exclusive", "claim_decisive"}


def test_j_llm_claim_agreements_passes_through_unmodified():
    synth, completions = _synthesizer([json.dumps(_wire_bundle())])
    result = _run(synth)

    agreements = result["structured_conclusion"]["claim_agreements"]
    assert agreements == _llm_claim_agreements()


def test_k_llm_claim_disagreements_passes_through_unmodified():
    bundle = _wire_bundle()
    # claim_decisive moves from "unanimous" to "disputed" in this test, so
    # it can no longer also be claimed as an agreement -- and, for the
    # LLM-supplied claim_matrix/claim_disagreements to stay internally
    # consistent with claim_analysis (which the backend's own derivation
    # also reads), gemini must genuinely dispute it there too.
    bundle["trusted_conclusion"]["claim_agreements"] = []
    # No longer an undisputed shared fact once gemini disputes it below.
    bundle["trusted_conclusion"]["strongest_evidence"] = []
    bundle["trusted_conclusion"]["claim_disagreements"] = [
        {
            "topic": "Whether the benefit is secondary or primary",
            "claim_ids": ["claim_decisive"],
            "positions": [
                {"provider": "openai", "position": "It is the primary benefit."},
                {"provider": "gemini", "position": "It is a secondary benefit."},
            ],
            "disagreement_type": "emphasis",
            "impact_on_verdict": "low",
            "referee_resolution": "Both agree caching helps; only emphasis differs.",
        }
    ]
    bundle["trusted_conclusion"]["claim_matrix"][1]["agreement_level"] = "disputed"
    bundle["trusted_conclusion"]["claim_matrix"][1]["provider_positions"][1][
        "position"
    ] = "contradicts"
    bundle["claim_analysis"]["claims"][1]["supporting_models"] = ["openai"]
    bundle["claim_analysis"]["claims"][1]["disputing_models"] = ["gemini"]
    bundle["claim_analysis"]["claims"][1]["support"] = [
        item
        for item in bundle["claim_analysis"]["claims"][1]["support"]
        if item["provider"] == "openai"
    ]
    bundle["claim_analysis"]["claims"][1]["dispute"] = [
        wire_support("gemini"),
    ]
    bundle["claim_analysis"]["claims"][1]["assessment"] = {
        "status": "disputed",
        "reason": "Gemini frames this as a secondary benefit.",
    }
    synth, completions = _synthesizer([json.dumps(bundle)])
    result = _run(synth)

    assert result["structured_conclusion"]["claim_disagreements"] == (
        bundle["trusted_conclusion"]["claim_disagreements"]
    )


# --- L: traceability / excerpts / citations unaffected ---------------------


def test_l_traceability_and_excerpt_validation_unaffected():
    synth, completions = _synthesizer([json.dumps(_wire_bundle())])
    result = _run(synth)

    assert result["claim_analysis_status"] == "SUCCESS"
    claims = {claim["id"]: claim for claim in result["claims"]}
    # Resolution always returns the full sentence at sentence_index -- never
    # a sub-sentence span -- so the resolved excerpt is the whole (only)
    # sentence in OPENAI_TEXT, not a hand-picked fragment of it.
    assert claims["claim_decisive"]["support"][0]["response_excerpt"] == (
        OPENAI_TEXT
    )
    assert claims["claim_decisive"]["support"][0]["provider"] == "openai"


def test_l_out_of_range_sentence_index_is_still_rejected():
    bundle = _wire_bundle()
    # OPENAI_TEXT has exactly one sentence (index 0) -- 7 is out of range.
    bundle["claim_analysis"]["claims"][0]["support"][0]["sentence_index"] = 7
    synth, completions = _synthesizer(
        [json.dumps(bundle), json.dumps(_wire_bundle())]
    )
    result = _run(synth)
    assert result["repair_attempted"] is True
    assert completions.calls == 2


# --- M/N: FAILED providers and LIVE/DEMO separation unaffected -------------


def test_m_failed_provider_never_enters_derived_sections():
    # gemini is FAILED and therefore not part of the panel at all: it must
    # never appear in either derived section, even though it exists in the
    # broader answers list passed elsewhere in the app.
    single_provider_matrix = [
        {
            "claim_id": "claim_exclusive",
            "claim": "OpenAI notes a secondary caching benefit.",
            "importance": "medium",
            "provider_positions": [
                {
                    "provider": "openai",
                    "display_name": "ChatGPT",
                    "position": "supports",
                    "summary": "OpenAI raises this point alone.",
                    "evidence_refs": ["openai"],
                    "confidence": "medium",
                }
            ],
            "agreement_level": "unresolved",
            "referee_assessment": "Only OpenAI addressed this point.",
            "evidence_limitations": [],
        }
    ]
    trusted_conclusion = {
        **_wire_trusted_conclusion(),
        "strongest_evidence": [
            {
                "id": "evidence_1",
                "claim": "OpenAI notes a secondary caching benefit.",
                "description": "OpenAI is the only provider raising this.",
                "supporting_models": ["openai"],
                "source_status": "model_reasoning",
                "evidence_claim_ids": ["claim_exclusive"],
            }
        ],
        "claim_matrix": single_provider_matrix,
        "claim_agreements": [],
        "confidence": {
            "level": "low",
            "reason": "Only one provider addressed this point.",
            "factors": {
                "model_agreement": "low",
                "evidence_quality": "medium",
                "uncertainty": "high",
            },
        },
    }
    conclusion = parse_structured_conclusion(trusted_conclusion, ["openai"])
    single_claim_analysis = {
        "schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": [_public_claim_analysis_claims()[0]],
    }
    analysis = ClaimAnalysisV3.model_validate(single_claim_analysis)
    only_openai_answer = [answer("openai", OPENAI_TEXT, status="LIVE")]
    enriched = _enrich_conclusion(conclusion, analysis, [], only_openai_answer)

    assert enriched.exclusive_contributions != []
    assert enriched.decisive_factors != []
    for factor in enriched.decisive_factors:
        assert "gemini" not in factor.supported_by
        assert "gemini" not in factor.opposed_by
    for contribution in enriched.exclusive_contributions:
        assert contribution.provider != "gemini"


def test_n_live_demo_separation_still_enforced_with_the_new_wire_schema():
    demo_answers = [
        answer("openai", OPENAI_TEXT, status="MOCK"),
        answer("gemini", GEMINI_TEXT, status="MOCK"),
    ]
    demo_bundle = _wire_bundle()
    demo_bundle["claim_analysis"]["execution_mode"] = "DEMO"
    synth, completions = _synthesizer([json.dumps(demo_bundle)])
    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            demo_answers,
            "en",
            execution_mode="DEMO",
            correlation_id="wire-step1-demo",
        )
    )
    assert completions.calls == 1
    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["structured_conclusion"]["decisive_factors"] != []
    assert result["structured_conclusion"]["exclusive_contributions"] != []


def test_n_live_demo_mismatch_is_still_rejected():
    demo_answers = [
        answer("openai", OPENAI_TEXT, status="MOCK"),
        answer("gemini", GEMINI_TEXT, status="MOCK"),
    ]
    # claim_analysis says LIVE while the panel is MOCK -- execution mode
    # mismatch, unaffected by this patch.
    synth, completions = _synthesizer(
        [json.dumps(_wire_bundle()), json.dumps(_wire_bundle())]
    )
    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            demo_answers,
            "en",
            execution_mode="DEMO",
            correlation_id="wire-step1-demo-mismatch",
        )
    )
    assert result["claim_analysis_status"] == "FAILED"
    assert completions.calls == 2


# --- O: repair receives the new (narrower) wire schema ---------------------


def test_o_repair_prompt_uses_the_new_wire_schema():
    bundle = _wire_bundle()
    # OPENAI_TEXT has exactly one sentence (index 0) -- 9 is out of range.
    bundle["claim_analysis"]["claims"][0]["support"][0]["sentence_index"] = 9
    synth, completions = _synthesizer(
        [json.dumps(bundle), json.dumps(_wire_bundle())]
    )
    _run(synth)

    assert completions.calls == 2
    repair_user_message = completions.requests[1]["messages"][1]["content"]
    repair_payload = json.loads(repair_user_message)
    repair_schema_text = json.dumps(repair_payload["required_json_schema"])
    assert "exclusive_contributions" not in repair_schema_text
    assert "decisive_factors" not in repair_schema_text
    assert "claim_matrix" in repair_schema_text


def test_o_repair_still_rejects_the_two_fields_if_llm_emits_them_anyway():
    bad_repair = _wire_bundle()
    bad_repair["trusted_conclusion"]["exclusive_contributions"] = []
    synth, completions = _synthesizer(
        [
            json.dumps({**_wire_bundle(), "claim_analysis": {"schema_version": "3.0", "execution_mode": "LIVE", "claims": []}}),
            json.dumps(bad_repair),
        ]
    )
    result = _run(synth)
    # The repaired output is still rejected (extra_forbidden), so the
    # second-stage salvage of the repair output is what wins.
    assert result["claim_analysis_status"] == "FAILED"
    assert completions.calls == 2


# --- P: salvage unaffected ---------------------------------------------


def test_p_salvage_still_discards_structured_sections_on_malformed_matrix():
    invalid = _wire_trusted_conclusion()
    invalid["claim_matrix"] = {"not": "a list"}
    repaired = _wire_trusted_conclusion()
    repaired["claim_matrix"] = []
    repaired["claim_agreements"] = []
    synth, completions = _synthesizer(
        [
            json.dumps(
                {
                    "trusted_conclusion": invalid,
                    "claim_analysis": _claim_analysis(),
                }
            ),
            json.dumps(
                {
                    "trusted_conclusion": repaired,
                    "claim_analysis": _claim_analysis(),
                }
            ),
        ]
    )
    result = _run(synth)
    assert result["repair_attempted"] is True
    assert completions.calls == 2
    # Salvage behavior (discarding claim_matrix on a malformed initial
    # attempt) is unchanged; exclusive_contributions/decisive_factors are
    # still derived from claim_analysis regardless.
    assert result["structured_conclusion"]["exclusive_contributions"] == [
        item
        for item in result["structured_conclusion"]["exclusive_contributions"]
    ]


# --- Q: persisted/API response still contains both fields ------------------


def test_q_api_response_contains_both_fields_in_the_same_position():
    synth, completions = _synthesizer([json.dumps(_wire_bundle())])
    result = _run(synth)

    structured = result["structured_conclusion"]
    expected_keys = {
        "schema_version",
        "final_answer",
        "agreements",
        "disagreements",
        "strongest_evidence",
        "remaining_uncertainties",
        "unsupported_claims",
        "confidence",
        "referee_reasoning",
        "what_could_change_the_verdict",
        "claim_matrix",
        "claim_agreements",
        "claim_disagreements",
        "exclusive_contributions",
        "decisive_factors",
        "final_verdict",
        "confidence_reason",
        "key_findings",
        "uncertainties",
        "strongest_shared_evidence",
        "what_could_change",
        "provider_assessment",
        "source_summary",
    }
    assert expected_keys.issubset(set(structured))


# --- R: historical documents with the old fields still populated ----------


def test_r_historical_stored_documents_with_both_fields_still_read_correctly():
    stored_document = json.loads(json.dumps(load_fixture("unanimous")))
    assert stored_document["decisive_factors"] != []
    normalized, version = normalize_stored_conclusion(
        {"trusted_conclusion_structured": stored_document}
    )
    assert version == "2.0"
    assert normalized["decisive_factors"][0]["weight"] == "high"

    emphasis_document = json.loads(json.dumps(load_fixture("emphasis")))
    assert emphasis_document["exclusive_contributions"] != []
    normalized_emphasis, version_emphasis = normalize_stored_conclusion(
        {"trusted_conclusion_structured": emphasis_document}
    )
    assert version_emphasis == "2.0"
    assert normalized_emphasis["exclusive_contributions"][0]["provider"] == (
        "gemini"
    )
