"""Phase 3 claim and citation traceability tests."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import eligible_synthesis_answers  # noqa: E402
from providers.sentence_segmenter import split_sentences  # noqa: E402
from providers.synthesizer import Synthesizer  # noqa: E402
from providers.traceability_schema import (  # noqa: E402
    extract_citations,
    merge_provider_citations,
    normalize_safe_url,
    normalize_stored_traceability,
    validate_claim_analysis,
)


OPENAI_TEXT = "Caching reduces repeated work. The current limit is ten requests."
GEMINI_TEXT = "Caching reduces repeated work. The current limit is twenty requests."
MISTRAL_TEXT = (
    "Caching reduces repeated work.\n"
    "Useful details:\n"
    "- It avoids repeated provider calls.\n"
    "- It lowers latency for equivalent questions."
)


def answer(provider, text, status="LIVE", citations=None):
    provider_ids = {
        "openai": "model-a",
        "gemini": "model-c",
        "mistral": "model-e",
    }
    provider_labels = {
        "openai": "ChatGPT",
        "gemini": "Gemini",
        "mistral": "Mistral",
    }
    provider_names = {
        "openai": "OpenAI",
        "gemini": "Google",
        "mistral": "Mistral AI",
    }
    return {
        "id": provider_ids[provider],
        "provider_response_id": provider,
        "provider_key": provider,
        "label": provider_labels[provider],
        "provider": provider_names[provider],
        "provider_status": status,
        "text": text,
        "citations": citations or [],
    }


def test_mistral_citations_keep_provider_provenance():
    citation = extract_citations(
        "Source: https://docs.mistral.ai/",
        "mistral",
    )[0]
    assert citation["provider"] == "mistral"
    assert citation["declared_by_models"] == ["mistral"]


def test_three_provider_claim_keeps_mistral_excerpts_and_deduplicates_equivalents():
    claim = supported_claim()
    claim["originating_models"].append("mistral")
    claim["supporting_models"].append("mistral")
    claim["support"].append(
        support("mistral", "Caching reduces repeated work.")
    )
    # Same OpenAI evidence with equivalent whitespace must not be repeated.
    claim["support"].append(
        support("openai", "Caching  reduces repeated work.")
    )

    parsed = validate_claim_analysis(
        claim_analysis([claim]),
        [
            answer("openai", OPENAI_TEXT),
            answer("gemini", GEMINI_TEXT),
            answer("mistral", MISTRAL_TEXT),
        ],
        [],
        "LIVE",
    )

    assert parsed.claims[0].supporting_models == [
        "openai",
        "gemini",
        "mistral",
    ]
    assert [item.provider for item in parsed.claims[0].support] == [
        "openai",
        "gemini",
        "mistral",
    ]


def support(provider, excerpt):
    return {
        "provider": provider,
        "response_excerpt": excerpt,
        "response_reference": {
            "provider_response_id": provider,
            "start_hint": excerpt[:20],
            "end_hint": excerpt[-20:],
        },
    }


def claim_analysis(claims, execution_mode="LIVE"):
    return {
        "schema_version": "3.0",
        "execution_mode": execution_mode,
        "claims": claims,
    }


def supported_claim(citation_ids=None):
    excerpt = "Caching reduces repeated work."
    return {
        "id": "claim_shared",
        "text": "Caching reduces repeated work.",
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai", "gemini"],
        "disputing_models": [],
        "support": [
            support("openai", excerpt),
            support("gemini", excerpt),
        ],
        "citation_ids": citation_ids or [],
        "assessment": {
            "status": "supported",
            "reason": "Both provider responses contain the same statement.",
        },
    }


def disputed_claim():
    return {
        "id": "claim_limit",
        "text": "The current request limit is ten.",
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai"],
        "disputing_models": ["gemini"],
        "support": [
            support("openai", "The current limit is ten requests."),
        ],
        "dispute": [
            support("gemini", "The current limit is twenty requests."),
        ],
        "citation_ids": [],
        "assessment": {
            "status": "disputed",
            "reason": "Gemini states a different current limit.",
        },
    }


def valid_conclusion():
    return {
        "schema_version": "2.0",
        "final_answer": "Caching helps, but the current limit is disputed.",
        "agreements": [
            {
                "id": "agreement_1",
                "claim": "Caching reduces repeated work.",
                "supporting_models": ["openai", "gemini"],
                "strength": "strong",
                "reason": "Both providers state it.",
                "supporting_claim_ids": ["claim_shared"],
            }
        ],
        "disagreements": [
            {
                "id": "disagreement_1",
                "topic": "Current limit",
                "positions": [
                    {
                        "model": "openai",
                        "position": "Ten requests.",
                        "evidence_claim_ids": ["claim_limit"],
                    },
                    {
                        "model": "gemini",
                        "position": "Twenty requests.",
                        "evidence_claim_ids": ["claim_limit"],
                    },
                ],
                "referee_assessment": "The supplied responses conflict.",
                "missing_information": "A current authoritative limit.",
                "disputing_claim_ids": ["claim_limit"],
            }
        ],
        "strongest_evidence": [
            {
                "id": "evidence_1",
                "claim": "Caching reduces repeated work.",
                "description": "The same exact statement appears twice.",
                "supporting_models": ["openai", "gemini"],
                "source_status": "model_reasoning",
                "evidence_claim_ids": ["claim_shared"],
            }
        ],
        "remaining_uncertainties": [
            {
                "id": "uncertainty_1",
                "description": "The current limit is unresolved.",
                "impact": "medium",
            }
        ],
        "unsupported_claims": [],
        "confidence": {
            "level": "medium",
            "reason": "The core point is shared, while the current limit conflicts.",
            "factors": {
                "model_agreement": "medium",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "referee_reasoning": "The shared caching claim is stronger than the disputed limit.",
        "what_could_change_the_verdict": [
            "A genuine independently verified current limit."
        ],
    }


def _sentence_index_for(text, excerpt):
    """Locate excerpt as a whole sentence of text (wire-shape test fixtures
    only): the sentence-index wire contract resolves whole sentences, never
    arbitrary substrings, so every wire fixture excerpt below must equal one
    full sentence exactly.
    """
    return split_sentences(text).index(excerpt)


def wire_support(provider, sentence_index, response_id=None):
    return {
        "provider": provider,
        "sentence_index": sentence_index,
        "provider_response_id": response_id or provider,
    }


def wire_judgment(providers, partially_supported_by=None):
    return {
        "importance": "medium",
        "referee_assessment": "Assessment for testing.",
        "evidence_limitations": [],
        "partially_supported_by": partially_supported_by or [],
        "provider_judgments": [
            {"provider": provider, "summary": f"{provider} summary for testing."}
            for provider in providers
        ],
    }


def wire_supported_claim(citation_ids=None):
    excerpt = "Caching reduces repeated work."
    return {
        "id": "claim_shared",
        "text": "Caching reduces repeated work.",
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai", "gemini"],
        "disputing_models": [],
        "support": [
            wire_support("openai", _sentence_index_for(OPENAI_TEXT, excerpt)),
            wire_support("gemini", _sentence_index_for(GEMINI_TEXT, excerpt)),
        ],
        "citation_ids": citation_ids or [],
        "assessment": {
            "status": "supported",
            "reason": "Both provider responses contain the same statement.",
        },
        "judgment": wire_judgment(["openai", "gemini"]),
    }


def wire_disputed_claim():
    return {
        "id": "claim_limit",
        "text": "The current request limit is ten.",
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai"],
        "disputing_models": ["gemini"],
        "support": [
            wire_support(
                "openai",
                _sentence_index_for(OPENAI_TEXT, "The current limit is ten requests."),
            ),
        ],
        "dispute": [
            wire_support(
                "gemini",
                _sentence_index_for(
                    GEMINI_TEXT, "The current limit is twenty requests."
                ),
            ),
        ],
        "citation_ids": [],
        "assessment": {
            "status": "disputed",
            "reason": "Gemini states a different current limit.",
        },
        "judgment": wire_judgment(["openai", "gemini"]),
    }


def valid_bundle():
    return {
        "trusted_conclusion": valid_conclusion(),
        "claim_analysis": claim_analysis(
            [wire_supported_claim(), wire_disputed_claim()]
        ),
    }


def test_three_provider_bundle_generates_conclusion_and_traceability():
    shared = wire_supported_claim()
    shared["originating_models"].append("mistral")
    shared["supporting_models"].append("mistral")
    shared["support"].append(
        wire_support(
            "mistral",
            _sentence_index_for(MISTRAL_TEXT, "Caching reduces repeated work."),
        )
    )
    shared["judgment"] = wire_judgment(["openai", "gemini", "mistral"])
    bundle = valid_bundle()
    bundle["claim_analysis"]["claims"][0] = shared
    bundle["trusted_conclusion"]["agreements"][0]["supporting_models"] = [
        "openai",
        "gemini",
        "mistral",
    ]
    bundle["trusted_conclusion"]["strongest_evidence"][0][
        "supporting_models"
    ] = ["openai", "gemini", "mistral"]

    synth, completions = synthesizer_with_outputs([json.dumps(bundle)])
    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            [
                answer("openai", OPENAI_TEXT),
                answer("gemini", GEMINI_TEXT),
                answer("mistral", MISTRAL_TEXT),
            ],
            "en",
        )
    )

    assert result["text"] == valid_conclusion()["final_answer"]
    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["claims"][0]["supporting_models"] == [
        "openai",
        "gemini",
        "mistral",
    ]
    assert completions.calls == 1


def test_shared_claim_supported_by_two_live_providers():
    parsed = validate_claim_analysis(
        claim_analysis([supported_claim()]),
        [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
        [],
        "LIVE",
    )
    assert parsed.claims[0].supporting_models == ["openai", "gemini"]
    assert len(parsed.claims[0].support) == 2


def test_disputed_claim_is_preserved():
    parsed = validate_claim_analysis(
        claim_analysis([disputed_claim()]),
        [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
        [],
        "LIVE",
    )
    assert parsed.claims[0].assessment.status == "disputed"
    assert parsed.claims[0].disputing_models == ["gemini"]
    assert parsed.claims[0].dispute[0].provider == "gemini"


def test_mistral_can_oppose_a_claim_with_a_real_excerpt():
    claim = {
        "id": "claim_limit_mistral",
        "text": "The current limit is ten requests.",
        "claim_type": "fact",
        "originating_models": ["openai", "mistral"],
        "supporting_models": ["openai"],
        "disputing_models": ["mistral"],
        "support": [
            support("openai", "The current limit is ten requests."),
        ],
        "dispute": [
            support("mistral", "The current limit is twenty requests."),
        ],
        "citation_ids": [],
        "assessment": {
            "status": "disputed",
            "reason": "Mistral states a different current limit.",
        },
    }
    parsed = validate_claim_analysis(
        claim_analysis([claim]),
        [
            answer("openai", OPENAI_TEXT),
            answer(
                "mistral",
                "Caching reduces repeated work. "
                "The current limit is twenty requests.",
            ),
        ],
        [],
        "LIVE",
    )
    assert parsed.claims[0].disputing_models == ["mistral"]
    assert parsed.claims[0].dispute[0].provider == "mistral"


def test_one_live_and_one_failed_excludes_failed_provider():
    eligible = eligible_synthesis_answers(
        [
            answer("openai", OPENAI_TEXT),
            answer("gemini", "", status="FAILED"),
        ],
        "LIVE",
    )
    assert [item["provider_key"] for item in eligible] == ["openai"]
    with pytest.raises(ValueError, match="FAILED or absent"):
        validate_claim_analysis(
            claim_analysis([supported_claim()]),
            eligible,
            [],
            "LIVE",
        )


def test_markdown_plain_named_and_metadata_citations_are_extracted():
    text = (
        "Read [Official report](https://example.com/report), then compare "
        "https://example.org/data.\nSource: Standards Handbook"
    )
    citations = extract_citations(
        text,
        "openai",
        [{"url": "https://provider.example/source", "title": "Provider source"}],
    )
    assert {item["extraction_method"] for item in citations} == {
        "provider_metadata",
        "markdown_link",
        "plain_text_url",
        "explicit_source_label",
    }
    named = next(item for item in citations if item["extraction_method"] == "explicit_source_label")
    assert named["url"] is None
    assert named["verification_status"] == "missing_url"
    assert named["title"] == "Standards Handbook"


def test_duplicate_url_normalization_preserves_provider_provenance():
    openai_citations = extract_citations(
        "[Report](https://EXAMPLE.com:443/report#section)",
        "openai",
    )
    gemini_citations = extract_citations(
        "See https://example.com/report.",
        "gemini",
    )
    merged = merge_provider_citations([openai_citations, gemini_citations])
    assert len(merged) == 1
    assert merged[0]["url"] == "https://example.com/report"
    assert merged[0]["declared_by_models"] == ["openai", "gemini"]
    assert {item["provider"] for item in merged[0]["provenance"]} == {
        "openai",
        "gemini",
    }


def test_unsafe_url_is_rejected_and_never_marked_verified():
    citations = extract_citations("[bad](javascript:alert(1))", "openai")
    assert len(citations) == 1
    assert citations[0]["verification_status"] == "invalid_url"
    assert citations[0]["domain"] is None
    assert normalize_safe_url("javascript:alert(1)") == (None, None)


def test_provider_citation_defaults_to_unverified():
    citation = extract_citations("https://example.com/evidence", "openai")[0]
    assert citation["verification_status"] == "unverified"
    assert citation["verification_evidence"] is None


def test_claim_excerpt_must_come_from_actual_provider_text():
    invalid = supported_claim()
    invalid["support"][0]["response_excerpt"] = "A fabricated excerpt."
    with pytest.raises(ValueError, match="excerpt is not present"):
        validate_claim_analysis(
            claim_analysis([invalid]),
            [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
            [],
            "LIVE",
        )


def test_dispute_excerpt_must_come_from_actual_provider_text():
    invalid = disputed_claim()
    invalid["dispute"][0]["response_excerpt"] = "A fabricated contrary excerpt."
    with pytest.raises(ValueError, match="dispute excerpt is not present"):
        validate_claim_analysis(
            claim_analysis([invalid]),
            [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
            [],
            "LIVE",
        )


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


def test_invalid_claim_json_gets_one_controlled_repair():
    invalid = valid_bundle()
    invalid["claim_analysis"]["claims"][0]["support"][0]["sentence_index"] = 9
    synth, completions = synthesizer_with_outputs(
        [json.dumps(invalid), json.dumps(valid_bundle())]
    )
    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
            "en",
        )
    )
    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["repair_attempted"] is True
    assert completions.calls == 2


def test_claim_failure_preserves_conclusion_without_mock_data():
    invalid = valid_bundle()
    invalid["claim_analysis"]["claims"][0]["support"][0]["sentence_index"] = 9
    synth, completions = synthesizer_with_outputs(
        [json.dumps(invalid), json.dumps(invalid)]
    )
    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
            "en",
        )
    )
    assert result["text"] == valid_conclusion()["final_answer"]
    assert result["claim_analysis_status"] == "FAILED"
    assert result["claims"] == []
    assert "MOCK" not in json.dumps(result)
    assert completions.calls == 2


def test_phase2_and_legacy_records_remain_compatible_without_claims():
    phase2 = {
        "execution_mode": "LIVE",
        "trusted_conclusion_structured": valid_conclusion(),
    }
    legacy = {"trusted_conclusion": "Old text-only conclusion."}
    assert normalize_stored_traceability(phase2) == ([], [], "legacy")
    assert normalize_stored_traceability(legacy) == ([], [], "legacy")


def test_pre_phase5_traceability_without_dispute_excerpts_remains_compatible():
    old_claim = disputed_claim()
    old_claim.pop("dispute")
    record = {
        "claim_schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": [old_claim],
        "citations": [],
    }
    claims, citations, schema_version = normalize_stored_traceability(record)
    assert schema_version == "3.0"
    assert citations == []
    assert claims[0]["dispute"] == []


def test_demo_claims_remain_separate_from_live_claims():
    demo_answers = [
        answer("openai", OPENAI_TEXT, status="MOCK"),
        answer("gemini", GEMINI_TEXT, status="MOCK"),
    ]
    parsed = validate_claim_analysis(
        claim_analysis([supported_claim()], execution_mode="DEMO"),
        demo_answers,
        [],
        "DEMO",
    )
    assert parsed.execution_mode == "DEMO"
    with pytest.raises(ValueError, match="execution mode"):
        validate_claim_analysis(
            claim_analysis([supported_claim()], execution_mode="DEMO"),
            demo_answers,
            [],
            "LIVE",
        )


def test_empty_claim_analysis_with_existing_agreement_uses_safe_fallback():
    empty = valid_bundle()
    empty["claim_analysis"]["claims"] = []
    synth, completions = synthesizer_with_outputs(
        [json.dumps(empty), json.dumps(empty)]
    )

    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
            "en",
        )
    )

    structured = result["structured_conclusion"]
    assert completions.calls == 2
    assert result["claim_analysis_status"] == "FAILED"
    assert structured["schema_version"] == "2.1"
    assert structured["key_findings"][0]["claim"] == (
        empty["trusted_conclusion"]["agreements"][0]["claim"]
    )
    assert structured["key_findings"][0]["supporting_providers"] == [
        "openai",
        "gemini",
    ]
    assert structured["key_findings"][0]["relevant_excerpts"] == []
    assert structured["key_findings"][0]["source_references"] == []


def test_empty_claim_analysis_without_evidence_does_not_create_fallback():
    empty = valid_bundle()
    empty["trusted_conclusion"]["agreements"] = []
    empty["trusted_conclusion"]["disagreements"] = []
    empty["trusted_conclusion"]["strongest_evidence"] = []
    empty["claim_analysis"]["claims"] = []
    synth, completions = synthesizer_with_outputs([json.dumps(empty)])

    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
            "en",
        )
    )

    assert completions.calls == 1
    assert result["claim_analysis_status"] == "SUCCESS"
    assert result["structured_conclusion"]["schema_version"] == "2.1"
    assert result["structured_conclusion"]["key_findings"] == []
    assert result["structured_conclusion"]["source_summary"] == []


def test_provider_labels_are_normalized_only_in_provider_key_fields():
    aliased = valid_bundle()
    conclusion = aliased["trusted_conclusion"]
    conclusion["agreements"][0]["supporting_models"][1] = "Google DeepMind"
    conclusion["disagreements"][0]["positions"][1]["model"] = (
        "Google DeepMind"
    )
    conclusion["strongest_evidence"][0]["supporting_models"][1] = (
        "Google DeepMind"
    )
    for claim in aliased["claim_analysis"]["claims"]:
        for field in (
            "originating_models",
            "supporting_models",
            "disputing_models",
        ):
            claim[field] = [
                "Google DeepMind" if value == "gemini" else value
                for value in claim.get(field, [])
            ]
        for excerpt in claim.get("support", []) + claim.get("dispute", []):
            if excerpt["provider"] == "gemini":
                excerpt["provider"] = "Google DeepMind"
    synth, completions = synthesizer_with_outputs([json.dumps(aliased)])

    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            [answer("openai", OPENAI_TEXT), answer("gemini", GEMINI_TEXT)],
            "en",
        )
    )

    assert completions.calls == 1
    assert result["claim_analysis_status"] == "SUCCESS"
    finding = result["structured_conclusion"]["key_findings"][0]
    assert finding["supporting_providers"] == ["openai", "gemini"]
    assert all(
        excerpt["provider"] in ("openai", "gemini")
        for excerpt in finding["relevant_excerpts"]
    )


def test_conclusion_trace_diagnostics_are_disabled_by_default(
    monkeypatch,
    caplog,
):
    monkeypatch.delenv("AI_REFEREE_TRACE_CONCLUSION", raising=False)
    synth, _ = synthesizer_with_outputs([json.dumps(valid_bundle())])
    with caplog.at_level(logging.INFO):
        asyncio.run(
            synth.synthesize(
                "Private diagnostic prompt",
                [
                    answer("openai", OPENAI_TEXT),
                    answer("gemini", GEMINI_TEXT),
                ],
                "en",
            )
        )
    assert "Structured conclusion trace:" not in caplog.text


def test_conclusion_trace_diagnostics_log_shape_without_content(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("AI_REFEREE_TRACE_CONCLUSION", "true")
    synth, _ = synthesizer_with_outputs([json.dumps(valid_bundle())])
    with caplog.at_level(logging.INFO):
        asyncio.run(
            synth.synthesize(
                "Private diagnostic prompt",
                [
                    answer("openai", OPENAI_TEXT),
                    answer("gemini", GEMINI_TEXT),
                ],
                "en",
            )
        )
    trace = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "Structured conclusion trace:" in record.getMessage()
    )
    assert '"schema_version": "2.1"' in trace
    assert '"key_findings_count": 2' in trace
    assert '"claim_count": 2' in trace
    assert '"normalized_providers": ["gemini", "openai"]' in trace
    assert "Private diagnostic prompt" not in trace
    assert "Caching reduces repeated work." not in trace
    assert "https://" not in trace


def test_conclusion_trace_validation_errors_do_not_log_sensitive_content(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("AI_REFEREE_TRACE_CONCLUSION", "true")
    invalid = valid_bundle()
    invalid["claim_analysis"]["claims"] = []
    synth, _ = synthesizer_with_outputs(
        [json.dumps(invalid), json.dumps(invalid)]
    )
    with caplog.at_level(logging.INFO):
        asyncio.run(
            synth.synthesize(
                "Sensitive user question",
                [
                    answer("openai", OPENAI_TEXT),
                    answer("gemini", GEMINI_TEXT),
                ],
                "en",
            )
        )
    trace = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "Structured conclusion trace:" in record.getMessage()
    )
    assert '"parse_status": "failed"' in trace
    assert '"validation_errors":' in trace
    assert "Sensitive user question" not in trace
    assert "Caching reduces repeated work." not in trace
    assert "https://" not in trace


def test_conclusion_is_generated_from_openai_and_mistral_when_gemini_failed():
    bundle = valid_bundle()
    conclusion = bundle["trusted_conclusion"]
    conclusion["disagreements"] = []
    bundle["claim_analysis"]["claims"] = [wire_supported_claim()]
    for collection, field in (
        (conclusion["agreements"], "supporting_models"),
        (conclusion["strongest_evidence"], "supporting_models"),
    ):
        for item in collection:
            item[field] = [
                "mistral" if provider == "gemini" else provider
                for provider in item[field]
            ]
    claim = bundle["claim_analysis"]["claims"][0]
    for field in ("originating_models", "supporting_models"):
        claim[field] = [
            "mistral" if provider == "gemini" else provider
            for provider in claim[field]
        ]
    for excerpt in claim["support"]:
        if excerpt["provider"] == "gemini":
            excerpt["provider"] = "mistral"
            excerpt["provider_response_id"] = "mistral"
    for item in claim["judgment"]["provider_judgments"]:
        if item["provider"] == "gemini":
            item["provider"] = "mistral"

    synth, completions = synthesizer_with_outputs([json.dumps(bundle)])
    result = asyncio.run(
        synth.synthesize(
            "Does caching help?",
            [
                answer("openai", OPENAI_TEXT),
                answer("gemini", "", status="FAILED"),
                answer("mistral", MISTRAL_TEXT),
            ],
            "en",
        )
    )

    assert completions.calls == 1
    assert result["text"] == conclusion["final_answer"]
    assert result["claim_analysis_status"] == "SUCCESS"
    finding = result["structured_conclusion"]["key_findings"][0]
    assert finding["supporting_providers"] == ["openai", "mistral"]
