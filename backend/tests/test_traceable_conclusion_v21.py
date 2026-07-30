"""Local fixtures for the traceable Trusted Conclusion 2.1 contract."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.conclusion_schema import normalize_stored_conclusion  # noqa: E402
from providers.synthesizer import Synthesizer  # noqa: E402
from providers.traceability_schema import extract_citations  # noqa: E402


def support(provider: str, excerpt: str) -> dict:
    return {
        "provider": provider,
        "response_excerpt": excerpt,
        "response_reference": {
            "provider_response_id": provider,
            "start_hint": excerpt[:20],
            "end_hint": excerpt[-20:],
        },
    }


def answer(provider: str, text: str, citations: list[dict]) -> dict:
    details = {
        "openai": ("model-a", "ChatGPT", "OpenAI"),
        "gemini": ("model-c", "Gemini", "Google"),
    }
    provider_id, label, organization = details[provider]
    return {
        "id": provider_id,
        "provider_response_id": provider,
        "provider_key": provider,
        "label": label,
        "provider": organization,
        "provider_status": "LIVE",
        "text": text,
        "citations": citations,
    }


def conclusion(
    final_answer: str,
    agreements: list[dict] | None = None,
    disagreements: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": "2.0",
        "final_answer": final_answer,
        "agreements": agreements or [],
        "disagreements": disagreements or [],
        "strongest_evidence": [],
        "remaining_uncertainties": [],
        "unsupported_claims": [],
        "confidence": {
            "level": "medium",
            "reason": "The conclusion is limited to the supplied responses.",
            "factors": {
                "model_agreement": "medium",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "referee_reasoning": (
            "Consensus describes the supplied panel and is not external proof."
        ),
        "what_could_change_the_verdict": [
            "Independent verification of the underlying evidence."
        ],
    }


def claim_analysis(claims: list[dict]) -> dict:
    return {
        "schema_version": "3.0",
        "execution_mode": "LIVE",
        "claims": claims,
    }


class FakeCompletions:
    def __init__(self, output: dict):
        self.output = json.dumps(output)
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.output)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
            model="test-synthesizer",
        )


def run_fixture(bundle: dict, answers: list[dict]) -> dict:
    synth = Synthesizer.__new__(Synthesizer)
    completions = FakeCompletions(bundle)
    synth.available = True
    synth._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    result = asyncio.run(
        synth.synthesize(
            "Test question",
            answers,
            "en",
            execution_mode="LIVE",
        )
    )
    assert completions.calls == 1
    return result


def test_two_providers_share_one_source_without_external_verification():
    excerpt = "Caching reduces repeated work."
    source_url = "https://example.com/report"
    openai_text = f"{excerpt} [Shared report]({source_url})."
    gemini_text = f"{excerpt} Source: {source_url}."
    openai_citations = extract_citations(openai_text, "openai")
    gemini_citations = extract_citations(gemini_text, "gemini")
    citation_id = openai_citations[0]["id"]
    claim = {
        "id": "claim_cache",
        "text": excerpt,
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai", "gemini"],
        "disputing_models": [],
        "support": [
            support("openai", excerpt),
            support("gemini", excerpt),
        ],
        "dispute": [],
        "citation_ids": [citation_id],
        "assessment": {
            "status": "supported",
            "reason": "Both supplied responses state the same claim.",
        },
    }
    agreement = {
        "id": "agreement_cache",
        "claim": excerpt,
        "supporting_models": ["openai", "gemini"],
        "strength": "strong",
        "reason": "Both providers make the same statement.",
        "supporting_claim_ids": ["claim_cache"],
    }

    result = run_fixture(
        {
            "trusted_conclusion": conclusion(
                "Caching reduces repeated work in the supplied scenario.",
                agreements=[agreement],
            ),
            "claim_analysis": claim_analysis([claim]),
        },
        [
            answer("openai", openai_text, openai_citations),
            answer("gemini", gemini_text, gemini_citations),
        ],
    )

    structured = result["structured_conclusion"]
    assert structured["schema_version"] == "2.1"
    assert structured["final_verdict"] == structured["final_answer"]
    assert structured["key_findings"][0]["status"] == "probable"
    assert structured["key_findings"][0]["evidence_strength"] == "strong"
    assert structured["source_summary"][0]["verification_status"] == (
        "shared_by_multiple_models"
    )
    assert structured["source_summary"][0]["cited_by"] == [
        "openai",
        "gemini",
    ]
    assert structured["source_summary"][0]["supports_claim_ids"] == [
        "claim_cache"
    ]


def test_disagreement_keeps_each_provider_source_and_exact_excerpt():
    openai_excerpt = "The current limit is ten requests."
    gemini_excerpt = "The current limit is twenty requests."
    openai_text = (
        f"{openai_excerpt} Source: https://openai.example/limits"
    )
    gemini_text = (
        f"{gemini_excerpt} Source: https://google.example/limits"
    )
    openai_citations = extract_citations(openai_text, "openai")
    gemini_citations = extract_citations(gemini_text, "gemini")
    claim = {
        "id": "claim_limit",
        "text": "The current request limit differs between the responses.",
        "claim_type": "fact",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai"],
        "disputing_models": ["gemini"],
        "support": [support("openai", openai_excerpt)],
        "dispute": [support("gemini", gemini_excerpt)],
        "citation_ids": [
            openai_citations[0]["id"],
            gemini_citations[0]["id"],
        ],
        "assessment": {
            "status": "disputed",
            "reason": "The provider responses state different limits.",
        },
    }
    disagreement = {
        "id": "disagreement_limit",
        "topic": "Current request limit",
        "positions": [
            {
                "model": "openai",
                "position": "The limit is ten.",
                "evidence_claim_ids": ["claim_limit"],
            },
            {
                "model": "gemini",
                "position": "The limit is twenty.",
                "evidence_claim_ids": ["claim_limit"],
            },
        ],
        "referee_assessment": "Neither position is externally verified.",
        "missing_information": "A current authoritative limit.",
        "disputing_claim_ids": ["claim_limit"],
    }

    result = run_fixture(
        {
            "trusted_conclusion": conclusion(
                "The current limit cannot be resolved from these responses.",
                disagreements=[disagreement],
            ),
            "claim_analysis": claim_analysis([claim]),
        },
        [
            answer("openai", openai_text, openai_citations),
            answer("gemini", gemini_text, gemini_citations),
        ],
    )

    finding = result["structured_conclusion"]["key_findings"][0]
    assert finding["status"] == "disputed"
    assert finding["supporting_providers"] == ["openai"]
    assert finding["dissenting_providers"] == ["gemini"]
    assert {item["text"] for item in finding["relevant_excerpts"]} == {
        openai_excerpt,
        gemini_excerpt,
    }
    assert len(result["structured_conclusion"]["source_summary"]) == 2


def test_no_provider_sources_produces_empty_source_summary():
    excerpt = "The supplied answers agree on the basic mechanism."
    openai_text = excerpt
    gemini_text = excerpt
    claim = {
        "id": "claim_mechanism",
        "text": excerpt,
        "claim_type": "interpretation",
        "originating_models": ["openai", "gemini"],
        "supporting_models": ["openai", "gemini"],
        "disputing_models": [],
        "support": [
            support("openai", excerpt),
            support("gemini", excerpt),
        ],
        "dispute": [],
        "citation_ids": [],
        "assessment": {
            "status": "supported",
            "reason": "Both supplied responses contain this interpretation.",
        },
    }
    payload = conclusion(
        "The panel agrees on the mechanism, but supplies no source references."
    )
    payload["referee_reasoning"] = (
        "The provider responses contain no usable source references; the "
        "agreement is consensus rather than independently verified proof."
    )

    result = run_fixture(
        {
            "trusted_conclusion": payload,
            "claim_analysis": claim_analysis([claim]),
        },
        [
            answer("openai", openai_text, []),
            answer("gemini", gemini_text, []),
        ],
    )

    structured = result["structured_conclusion"]
    assert structured["source_summary"] == []
    assert structured["key_findings"][0]["source_references"] == []
    assert "no usable source references" in structured["referee_reasoning"]


def test_legacy_v2_record_still_normalizes_without_new_fields():
    old = conclusion("A legacy structured answer.")
    normalized, version = normalize_stored_conclusion(
        {"trusted_conclusion_structured": old}
    )
    assert version == "2.0"
    assert normalized["final_answer"] == "A legacy structured answer."
    assert "key_findings" not in normalized
