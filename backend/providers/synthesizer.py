"""Validated Trusted Conclusion 2.0 and claim-traceability synthesis.

The synthesizer receives only provider results selected by the comparison
engine. Provider citations are extracted deterministically before synthesis;
the model may only reference their IDs and may never create new URLs.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Iterable, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from .base import estimate_cost
from .conclusion_schema import (
    TrustedConclusionV2,
    parse_structured_conclusion,
)
from .traceability_schema import (
    ClaimAnalysisV3,
    associate_citations_with_claims,
    merge_provider_citations,
    validate_claim_analysis,
)
from .translator import LANG_NAMES

log = logging.getLogger(__name__)

SYNTH_MODEL = os.environ.get("SYNTH_MODEL", "gpt-5.4-mini").strip()


class SynthesisFailure(RuntimeError):
    """Safe, user-displayable Trusted Conclusion synthesis failure."""


class SynthesisBundleV3(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trusted_conclusion: TrustedConclusionV2
    claim_analysis: ClaimAnalysisV3


class Synthesizer:
    """Produce a validated conclusion and independently traceable claim set."""

    def __init__(self) -> None:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.available = bool(key)
        self._client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=key) if key else None

    async def synthesize(
        self,
        prompt: str,
        answers: Iterable[dict],
        target_lang: str,
        audience: str = "professional",
        fmt: str = "paragraph",
        execution_mode: str = "LIVE",
    ) -> dict:
        if not self._client:
            raise SynthesisFailure(
                "Trusted Conclusion is unavailable because the synthesis "
                "provider is not configured."
            )

        expected_status = "MOCK" if execution_mode == "DEMO" else "LIVE"
        clean = [
            answer
            for answer in answers
            if (answer.get("text") or "").strip()
            and str(answer.get("provider_status") or "").upper() == expected_status
        ]
        if not clean:
            raise SynthesisFailure(
                "Trusted Conclusion is unavailable because no provider "
                "returned usable evidence."
            )

        allowed_providers = sorted(
            {
                str(answer.get("provider_key") or answer.get("id") or "")
                .strip()
                .lower()
                for answer in clean
                if answer.get("provider_key") or answer.get("id")
            }
        )
        citations = merge_provider_citations(
            answer.get("citations") or []
            for answer in clean
        )
        target_name = LANG_NAMES.get(target_lang, "English")
        panel_payload = [
            {
                "provider_key": answer.get("provider_key"),
                "provider_response_id": (
                    answer.get("provider_response_id")
                    or answer.get("provider_key")
                ),
                "provider_label": answer.get("label"),
                "provider_organization": answer.get("provider"),
                "provider_status": answer.get("provider_status"),
                "response": answer["text"].strip(),
                "provider_declared_citations": [
                    _citation_for_prompt(citation)
                    for citation in citations
                    if answer.get("provider_key")
                    in (citation.get("declared_by_models") or [])
                ],
            }
            for answer in clean
        ]

        schema = SynthesisBundleV3.model_json_schema()
        system = _system_prompt(
            target_name=target_name,
            audience=audience,
            fmt=fmt,
            allowed_providers=allowed_providers,
            execution_mode=("DEMO" if execution_mode == "DEMO" else "LIVE"),
        )
        user_message = json.dumps(
            {
                "user_question": prompt,
                "target_language": target_lang,
                "allowed_provider_keys": allowed_providers,
                "provider_responses": panel_payload,
                "available_citations": [
                    _citation_for_prompt(citation)
                    for citation in citations
                ],
                "required_json_schema": schema,
            },
            ensure_ascii=False,
        )

        start = time.perf_counter()
        total_input_tokens = 0
        total_output_tokens = 0
        repair_attempted = False

        raw, usage, model_used = await self._request_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ]
        )
        total_input_tokens += usage["input_tokens"]
        total_output_tokens += usage["output_tokens"]

        try:
            parsed = _parse_bundle(
                raw,
                allowed_providers,
                clean,
                citations,
                execution_mode,
            )
        except Exception as first_error:
            first_valid_conclusion = _salvage_conclusion(
                raw,
                allowed_providers,
            )
            repair_attempted = True
            raw, usage, repair_model = await self._request_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "Repair the JSON so it exactly matches the supplied "
                            "schema. Do not add facts, source names, citation IDs "
                            "or URLs. Every response_excerpt must be copied from "
                            "the matching provider response. Return JSON only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "allowed_provider_keys": allowed_providers,
                                "available_citation_ids": [
                                    citation["id"] for citation in citations
                                ],
                                "provider_responses": panel_payload,
                                "required_json_schema": schema,
                                "validation_error": (
                                    f"{type(first_error).__name__}: "
                                    f"{str(first_error)[:1500]}"
                                ),
                                "invalid_output": raw[:20000],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
            total_input_tokens += usage["input_tokens"]
            total_output_tokens += usage["output_tokens"]
            model_used = repair_model or model_used
            try:
                parsed = _parse_bundle(
                    raw,
                    allowed_providers,
                    clean,
                    citations,
                    execution_mode,
                )
            except Exception as repair_error:
                # Preserve a valid Phase 2 conclusion when only claim analysis
                # failed. Claim links are stripped to avoid dangling references.
                conclusion = (
                    _salvage_conclusion(raw, allowed_providers)
                    or first_valid_conclusion
                )
                if conclusion is None:
                    log.warning(
                        "Synthesis validation failed after repair: %s",
                        type(repair_error).__name__,
                    )
                    raise SynthesisFailure(
                        "Trusted Conclusion could not be validated after one "
                        "repair attempt."
                    ) from repair_error
                parsed = {
                    "conclusion": conclusion,
                    "claim_analysis": None,
                    "claim_analysis_status": "FAILED",
                    "claim_analysis_error": (
                        "Claim traceability could not be validated after one "
                        "repair attempt."
                    ),
                    "citations": citations,
                }

        conclusion: TrustedConclusionV2 = parsed["conclusion"]
        analysis: Optional[ClaimAnalysisV3] = parsed["claim_analysis"]
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "text": conclusion.final_answer,
            "structured_conclusion": conclusion.model_dump(),
            "schema_version": conclusion.schema_version,
            "claims": (
                [claim.model_dump() for claim in analysis.claims]
                if analysis
                else []
            ),
            "citations": parsed["citations"],
            "claim_schema_version": analysis.schema_version if analysis else None,
            "claim_analysis_status": parsed["claim_analysis_status"],
            "claim_analysis_error": parsed["claim_analysis_error"],
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "latency_ms": latency_ms,
            "cost_usd": estimate_cost(
                model_used,
                total_input_tokens,
                total_output_tokens,
            ),
            "model_used": model_used,
            "language": target_lang,
            "repair_attempted": repair_attempted,
        }

    async def _request_json(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[str, dict[str, int], str]:
        try:
            response = await self._client.chat.completions.create(
                model=SYNTH_MODEL,
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            log.warning(
                "Trusted Conclusion provider request failed: %s",
                type(exc).__name__,
            )
            raise SynthesisFailure(
                "Trusted Conclusion synthesis provider is currently unavailable."
            ) from exc

        raw = (response.choices[0].message.content or "").strip()
        usage = response.usage
        return (
            raw,
            {
                "input_tokens": int(
                    getattr(usage, "prompt_tokens", 0) or 0
                ),
                "output_tokens": int(
                    getattr(usage, "completion_tokens", 0) or 0
                ),
            },
            getattr(response, "model", SYNTH_MODEL) or SYNTH_MODEL,
        )


def _system_prompt(
    target_name: str,
    audience: str,
    fmt: str,
    allowed_providers: list[str],
    execution_mode: str,
) -> str:
    return (
        "You are AI Referee's Consensus and Claim Traceability Engine. Use "
        "only the supplied provider responses. Do not use outside knowledge "
        "as evidence.\n\n"
        "Return one JSON object matching the supplied schema. Do not return "
        "Markdown or prose outside JSON.\n\n"
        f"Write every human-readable field in {target_name}. Audience: "
        f"{audience}. Preferred answer format: {fmt}.\n\n"
        "Rules:\n"
        "- final_answer must directly and fully answer the question.\n"
        "- Extract only material claims relevant to the verdict.\n"
        "- Use stable claim IDs such as claim_1, claim_2.\n"
        "- Agreements require two distinct supplied providers.\n"
        "- Do not manufacture disagreements.\n"
        "- A response_excerpt must be a short exact excerpt copied from that "
        "provider response; never paraphrase inside response_excerpt.\n"
        "- provider_response_id must exactly match the supplied ID.\n"
        "- supporting, disputing and originating models may use only: "
        f"{', '.join(allowed_providers)}.\n"
        f"- claim_analysis.execution_mode must be {execution_mode}.\n"
        "- Only use citation IDs supplied in available_citations, and only "
        "when the provider explicitly connects that citation to the claim.\n"
        "- Do not create URLs, citation IDs, source titles or publications.\n"
        "- Provider citations are unverified. Never claim independent "
        "verification or turn a citation into proof of truth.\n"
        "- FAILED providers are absent and cannot support or dispute claims.\n"
        "- supporting_claim_ids, disputing_claim_ids, evidence_claim_ids and "
        "unsupported_claim_ids must reference claim IDs in claim_analysis.\n"
        "- Confidence is high, medium or low only; never output a confidence "
        "percentage.\n"
        "- State uncertainty when the evidence is limited.\n"
        "- Empty optional sections must be empty arrays."
    )


def _parse_bundle(
    raw: str,
    allowed_providers: list[str],
    answers: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    execution_mode: str,
) -> dict[str, Any]:
    payload = json.loads(_extract_json_object(raw))

    # Backward compatibility for focused Phase 2 tests and stored workflows.
    if "trusted_conclusion" not in payload:
        conclusion = parse_structured_conclusion(payload, allowed_providers)
        return {
            "conclusion": conclusion,
            "claim_analysis": None,
            "claim_analysis_status": "NOT_AVAILABLE",
            "claim_analysis_error": None,
            "citations": citations,
        }

    bundle = SynthesisBundleV3.model_validate(payload)
    conclusion = parse_structured_conclusion(
        bundle.trusted_conclusion.model_dump(),
        allowed_providers,
    )
    analysis = validate_claim_analysis(
        bundle.claim_analysis.model_dump(),
        answers,
        citations,
        execution_mode,
    )
    _validate_conclusion_claim_references(conclusion, analysis)
    return {
        "conclusion": conclusion,
        "claim_analysis": analysis,
        "claim_analysis_status": "SUCCESS",
        "claim_analysis_error": None,
        "citations": associate_citations_with_claims(citations, analysis),
    }


def _validate_conclusion_claim_references(
    conclusion: TrustedConclusionV2,
    analysis: ClaimAnalysisV3,
) -> None:
    known = {claim.id for claim in analysis.claims}
    references: list[str] = []
    for agreement in conclusion.agreements:
        references.extend(agreement.supporting_claim_ids)
    for disagreement in conclusion.disagreements:
        references.extend(disagreement.disputing_claim_ids)
    for evidence in conclusion.strongest_evidence:
        references.extend(evidence.evidence_claim_ids)
    for unsupported in conclusion.unsupported_claims:
        references.extend(unsupported.unsupported_claim_ids)
    unknown = sorted(set(references) - known)
    if unknown:
        raise ValueError(
            "Trusted Conclusion references unknown claim IDs: "
            + ", ".join(unknown)
        )


def _salvage_conclusion(
    raw: str,
    allowed_providers: list[str],
) -> Optional[TrustedConclusionV2]:
    try:
        payload = json.loads(_extract_json_object(raw))
        candidate = payload.get("trusted_conclusion", payload)
        if not isinstance(candidate, dict):
            return None
        candidate = json.loads(json.dumps(candidate))
        for item in candidate.get("agreements", []):
            item["supporting_claim_ids"] = []
        for item in candidate.get("disagreements", []):
            item["disputing_claim_ids"] = []
        for item in candidate.get("strongest_evidence", []):
            item["evidence_claim_ids"] = []
        for item in candidate.get("unsupported_claims", []):
            item["unsupported_claim_ids"] = []
        return parse_structured_conclusion(candidate, allowed_providers)
    except Exception:
        return None


def _extract_json_object(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Synthesizer did not return a JSON object")
    return text[start : end + 1]


def _citation_for_prompt(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": citation.get("id"),
        "declared_by_models": citation.get("declared_by_models") or [],
        "title": citation.get("title"),
        "url": citation.get("url"),
        "domain": citation.get("domain"),
        "source_type": citation.get("source_type"),
        "verification_status": citation.get("verification_status"),
        "extraction_method": citation.get("extraction_method"),
    }
