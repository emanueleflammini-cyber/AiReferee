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
from functools import lru_cache
from typing import Any, Iterable, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .base import estimate_cost
from .conclusion_schema import (
    TrustedConclusionV2,
    TrustedConclusionV21,
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
TRACE_CONCLUSION_ENV = "AI_REFEREE_TRACE_CONCLUSION"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_MAX_VALIDATION_ERRORS_LOGGED = 20
_SAFE_DIAGNOSTIC_VALUE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_PROVIDER_ALIASES = {
    "openai": "openai",
    "chatgpt": "openai",
    "gemini": "gemini",
    "google": "gemini",
    "google deepmind": "gemini",
    "mistral": "mistral",
    "mistral ai": "mistral",
}


class SynthesisFailure(RuntimeError):
    """Safe, user-displayable Trusted Conclusion synthesis failure."""

    def __init__(
        self,
        message: str,
        *,
        telemetry: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.telemetry = dict(telemetry or {})


class SynthesisBundleV3(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trusted_conclusion: TrustedConclusionV2
    claim_analysis: ClaimAnalysisV3

    @model_validator(mode="after")
    def require_claims_for_structured_evidence(self) -> "SynthesisBundleV3":
        has_structured_evidence = bool(
            self.trusted_conclusion.agreements
            or self.trusted_conclusion.strongest_evidence
        )
        if has_structured_evidence and not self.claim_analysis.claims:
            raise ValueError(
                "agreements or strongest_evidence require traceable claims"
            )
        return self


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
        correlation_id: Optional[str] = None,
    ) -> dict:
        # `correlation_id` (perf/request-timeline-observability, purely
        # additive): server.py passes its query_id so the initial-call/
        # repair-pass log lines below can be correlated to one compare_query
        # request. Never logged alongside prompt/answer/response content —
        # only IDs, statuses and durations. Does not affect the request
        # sent to SYNTH_MODEL, its timeout, its retries, or validation.
        cid = correlation_id or "unknown"
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
        provider_labels = {
            str(answer.get("provider_key") or answer.get("id") or "")
            .strip()
            .lower(): str(
                answer.get("label")
                or answer.get("provider_key")
                or answer.get("id")
                or ""
            ).strip()
            for answer in clean
            if answer.get("provider_key") or answer.get("id")
        }
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
        schema_json = json.dumps(schema, ensure_ascii=False)
        panel_payload_json = json.dumps(panel_payload, ensure_ascii=False)
        system = _system_prompt(
            target_name=target_name,
            audience=audience,
            fmt=fmt,
            allowed_providers=allowed_providers,
            provider_labels=provider_labels,
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
        total_reported_tokens = 0
        total_cost_usd = 0.0
        repair_attempted = False
        synthesis_initial_call_ms = 0
        synthesis_repair_ms: Optional[int] = None
        model_used = SYNTH_MODEL
        attempt_metadata: list[dict[str, Any]] = []

        log.info(
            "synthesis_prompt_dimensions query_id=%s stage=initial "
            "system_prompt_chars=%d schema_chars=%d panel_payload_chars=%d "
            "request_prompt_chars=%d",
            cid,
            len(system),
            len(schema_json),
            len(panel_payload_json),
            len(user_message),
        )
        log.info("synthesis_initial_call_started query_id=%s model=%s", cid, SYNTH_MODEL)
        _initial_call_start = time.perf_counter()
        try:
            raw, usage, model_used, initial_metadata = await self._request_json(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ]
            )
        except SynthesisFailure as exc:
            synthesis_initial_call_ms = int(
                (time.perf_counter() - _initial_call_start) * 1000
            )
            exc.telemetry = _synthesis_telemetry(
                model_used=model_used,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_reported_tokens,
                latency_ms=int((time.perf_counter() - start) * 1000),
                cost_usd=total_cost_usd,
                repair_attempted=False,
                attempts=attempt_metadata,
            )
            _log_failed_attempt_totals(cid, exc.telemetry)
            raise
        synthesis_initial_call_ms = int((time.perf_counter() - _initial_call_start) * 1000)
        log.info(
            "synthesis_initial_call_completed query_id=%s duration_ms=%d",
            cid, synthesis_initial_call_ms,
        )
        _trace_raw_payload("initial_raw", raw)
        total_input_tokens += usage["input_tokens"]
        total_output_tokens += usage["output_tokens"]
        total_reported_tokens += usage["total_tokens"]
        total_cost_usd += estimate_cost(
            model_used,
            usage["input_tokens"],
            usage["output_tokens"],
        )
        initial_metadata.update(
            {"stage": "initial", "latency_ms": synthesis_initial_call_ms}
        )
        attempt_metadata.append(initial_metadata)
        _log_openai_response_metadata(cid, "initial", initial_metadata)

        try:
            parsed = _parse_bundle(
                raw,
                allowed_providers,
                clean,
                citations,
                execution_mode,
            )
        except Exception as first_error:
            _log_parse_failure(cid, "initial", model_used, first_error)
            _trace_validation_error(
                "initial_parse_failed",
                first_error,
                query_id=cid,
                model=model_used,
            )
            log.info(
                "synthesis_salvage_started query_id=%s stage=initial",
                cid,
            )
            first_valid_conclusion = _salvage_conclusion(
                raw,
                allowed_providers,
            )
            log.info(
                "synthesis_salvage_completed query_id=%s stage=initial status=%s",
                cid,
                "SUCCESS" if first_valid_conclusion is not None else "FAILED",
            )
            repair_attempted = True
            log.info(
                "synthesis_repair_started query_id=%s reason=%s",
                cid, type(first_error).__name__,
            )
            repair_system = (
                "Repair the JSON so it exactly matches the supplied "
                "schema. Do not add facts, source names, citation IDs "
                "or URLs. Every response_excerpt must be copied from "
                "the matching provider response. Return JSON only."
            )
            diagnostic_instruction = _repair_diagnostic_instruction(first_error)
            if diagnostic_instruction:
                repair_system = f"{repair_system} {diagnostic_instruction}"
            invalid_output = raw[:20000]
            repair_user_message = json.dumps(
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
                    "invalid_output": invalid_output,
                },
                ensure_ascii=False,
            )
            log.info(
                "synthesis_prompt_dimensions query_id=%s stage=repair "
                "system_prompt_chars=%d schema_chars=%d panel_payload_chars=%d "
                "invalid_output_chars=%d repair_prompt_chars=%d",
                cid,
                len(repair_system),
                len(schema_json),
                len(panel_payload_json),
                len(invalid_output),
                len(repair_user_message),
            )
            _repair_call_start = time.perf_counter()
            try:
                raw, usage, repair_model, repair_metadata = await self._request_json(
                    [
                        {
                            "role": "system",
                            "content": repair_system,
                        },
                        {
                            "role": "user",
                            "content": repair_user_message,
                        },
                    ]
                )
            except SynthesisFailure as exc:
                synthesis_repair_ms = int(
                    (time.perf_counter() - _repair_call_start) * 1000
                )
                exc.telemetry = _synthesis_telemetry(
                    model_used=model_used,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    total_tokens=total_reported_tokens,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    cost_usd=total_cost_usd,
                    repair_attempted=True,
                    attempts=attempt_metadata,
                )
                _log_failed_attempt_totals(cid, exc.telemetry)
                raise
            synthesis_repair_ms = int((time.perf_counter() - _repair_call_start) * 1000)
            log.info(
                "synthesis_repair_completed query_id=%s duration_ms=%d",
                cid, synthesis_repair_ms,
            )
            _trace_raw_payload("repair_raw", raw)
            total_input_tokens += usage["input_tokens"]
            total_output_tokens += usage["output_tokens"]
            total_reported_tokens += usage["total_tokens"]
            model_used = repair_model or model_used
            total_cost_usd += estimate_cost(
                repair_model or model_used,
                usage["input_tokens"],
                usage["output_tokens"],
            )
            repair_metadata.update(
                {"stage": "repair", "latency_ms": synthesis_repair_ms}
            )
            attempt_metadata.append(repair_metadata)
            _log_openai_response_metadata(cid, "repair", repair_metadata)
            try:
                parsed = _parse_bundle(
                    raw,
                    allowed_providers,
                    clean,
                    citations,
                    execution_mode,
                )
            except Exception as repair_error:
                _log_parse_failure(cid, "repair", model_used, repair_error)
                _trace_validation_error(
                    "repair_parse_failed",
                    repair_error,
                    query_id=cid,
                    model=model_used,
                )
                # Preserve a valid Phase 2 conclusion when only claim analysis
                # failed. Claim links are stripped to avoid dangling references.
                log.info(
                    "synthesis_salvage_started query_id=%s stage=repair",
                    cid,
                )
                repair_valid_conclusion = _salvage_conclusion(
                    raw,
                    allowed_providers,
                )
                log.info(
                    "synthesis_salvage_completed query_id=%s stage=repair status=%s",
                    cid,
                    "SUCCESS" if repair_valid_conclusion is not None else "FAILED",
                )
                conclusion = repair_valid_conclusion or first_valid_conclusion
                if conclusion is None:
                    log.warning(
                        "Synthesis validation failed after repair: %s",
                        type(repair_error).__name__,
                    )
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    telemetry = _synthesis_telemetry(
                        model_used=model_used,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        total_tokens=total_reported_tokens,
                        latency_ms=latency_ms,
                        cost_usd=total_cost_usd,
                        repair_attempted=True,
                        attempts=attempt_metadata,
                    )
                    _log_failed_attempt_totals(cid, telemetry)
                    raise SynthesisFailure(
                        "Trusted Conclusion could not be validated after one "
                        "repair attempt.",
                        telemetry=telemetry,
                    ) from repair_error
                conclusion = _enrich_conclusion_without_claim_analysis(
                    conclusion,
                    citations,
                    clean,
                    execution_mode,
                )
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
        _trace_result(
            conclusion,
            analysis,
            parsed["claim_analysis_status"],
            clean,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "synthesis_call_breakdown query_id=%s repair_required=%s "
            "initial_call_ms=%d repair_ms=%d total_ms=%d",
            cid, repair_attempted, synthesis_initial_call_ms,
            synthesis_repair_ms or 0, latency_ms,
        )
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
            "total_tokens": total_reported_tokens,
            "latency_ms": latency_ms,
            "cost_usd": total_cost_usd,
            "model_used": model_used,
            "language": target_lang,
            "repair_attempted": repair_attempted,
            "attempt_metadata": attempt_metadata,
        }

    async def _request_json(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[str, dict[str, int], str, dict[str, Any]]:
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
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(
            getattr(usage, "total_tokens", 0)
            or (input_tokens + output_tokens)
        )
        model_used = getattr(response, "model", SYNTH_MODEL) or SYNTH_MODEL
        first_choice = response.choices[0] if response.choices else None
        metadata = {
            "request_id": _safe_diagnostic_value(
                getattr(response, "_request_id", None)
            ),
            "finish_reason": _safe_diagnostic_value(
                getattr(first_choice, "finish_reason", None)
            ),
            "model": _safe_diagnostic_value(model_used),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
        return (
            raw,
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            model_used,
            metadata,
        )


def _system_prompt(
    target_name: str,
    audience: str,
    fmt: str,
    allowed_providers: list[str],
    provider_labels: dict[str, str],
    execution_mode: str,
) -> str:
    participating_labels = [
        provider_labels.get(provider, provider)
        for provider in allowed_providers
    ]
    label_list = _human_label_list(participating_labels)
    return (
        "You are AI Referee's Consensus and Claim Traceability Engine. Use "
        "only the supplied provider responses. Do not use outside knowledge "
        "as evidence.\n\n"
        "Return one JSON object matching the supplied schema. Do not return "
        "Markdown or prose outside JSON.\n\n"
        f"Write every human-readable field in {target_name}. Audience: "
        f"{audience}. Preferred answer format: {fmt}. This translation "
        "requirement does NOT apply to support[].response_excerpt, "
        "dispute[].response_excerpt, or response_reference start_hint/"
        "end_hint: those are verbatim evidence and must stay in whatever "
        "language the original provider response used, unmodified.\n\n"
        "Rules:\n"
        "- final_answer must directly and fully answer the question.\n"
        "- final_answer must be specific to the supplied evidence. Avoid a "
        "generic summary that could apply to a different question.\n"
        "- Act as an impartial referee, not a summarizer. Explain how the "
        "provider responses support the verdict; never rank one provider as "
        "the best AI overall or favor a provider by default.\n"
        "- In human-readable narrative fields, identify participating "
        "providers with the exact provider_label supplied in "
        "provider_responses. Keep schema provider fields normalized to "
        "allowed_provider_keys.\n"
        "- The only participating provider labels in this execution are: "
        f"{label_list}. Do not name an absent or failed provider as a "
        "participant.\n"
        "- Describe each material agreement by naming the providers involved "
        "and the specific proposition they share. Never use only a generic "
        "statement such as 'the models agree'. Use wording equivalent in the "
        f"target language to '{label_list} agree that ...', adapted "
        "grammatically to the number of providers.\n"
        "- Reserve disagreements for genuinely incompatible positions. "
        "Different emphasis, different caution, extra non-contradicted "
        "information, and omission are not disagreements.\n"
        "- For every genuine disagreement, describe each provider's specific "
        "position and explain qualitatively whether and why the divergence "
        "has a low, medium, or high impact on the final verdict.\n"
        "- If no genuine disagreement exists, leave disagreements empty and "
        "state clearly in final_answer or referee_reasoning that no "
        "substantial contradiction emerged; describe any differences as "
        "emphasis, caution, detail, or omission as appropriate.\n"
        "- Treat a material contribution made by only one provider as an "
        "exclusive contribution, not automatically as truth or disagreement. "
        "Describe it using existing narrative or evidence fields and assess "
        "whether the supplied response evidence supports it.\n"
        "- Every conclusion statement must be attributable to at least one "
        "supplied LIVE provider. If you make an inference, label it explicitly "
        "as an inference, identify the provider response elements it derives "
        "from, and never present it as a provider-supplied fact.\n"
        "- Motivate the verdict only from responses actually supplied. "
        "Explicitly state when information or verifiable sources are missing.\n"
        "- Distinguish facts, interpretations, recommendations and predictions "
        "using claim_type. Agreement between models is consensus, not proof.\n"
        f"- This execution contains exactly {len(allowed_providers)} usable "
        "provider response(s). Never claim that more providers participated "
        "or agreed than are present in allowed_provider_keys.\n"
        "- Extract only the claims that materially decide the verdict. "
        "Merge semantically equivalent claims into one; never split a "
        "single point into trivial sub-claims just to raise the count.\n"
        "- Build claim_matrix from those decisive claims: target 3 to 5 "
        "items, prioritizing coverage of what actually changes the "
        "verdict over exhaustiveness. Use 3 for a simple, narrowly-scoped "
        "question with few genuinely distinct decisive points. Go to 4 or "
        "5 only when the question has that many materially distinct "
        "decisive points. Exceed 5 only if the supplied evidence "
        "genuinely contains more decisive points than that -- do not pad "
        "claim_matrix to reach a target count.\n"
        "- Every claim_matrix claim_id must exist in claim_analysis.claims. "
        "For every participating provider, distinguish supports, "
        "partially_supports, contradicts, uncertain, and not_mentioned. "
        "Omission is not contradiction.\n"
        "- claim_agreements may reference only IDs from claim_matrix.\n"
        "- exclusive_contributions contain useful material supplied by only "
        "one provider. Mark whether each contribution is supported within "
        "that response, unverified, inferential, or contradicted; uniqueness "
        "does not make it true.\n"
        "- decisive_factors must explain which supplied evidence materially "
        "led to the final verdict. The narrative verdict, claim_matrix, "
        "claim_agreements, claim_disagreements, and decisive_factors must be "
        "mutually coherent.\n"
        "- evidence_refs may use only provider_response_id values and "
        "citation IDs supplied in the request. Never create an evidence "
        "reference.\n"
        "- When agreements or strongest_evidence is non-empty, "
        "claim_analysis.claims must contain at least one corresponding claim. "
        "Do not return an empty claims array in that case.\n"
        "- Every claim must derive exclusively from the supplied provider "
        "responses. Never invent a claim to satisfy the schema.\n"
        "- supporting_models and disputing_models must use normalized provider "
        "keys from allowed_provider_keys, never provider labels or organization "
        "names.\n"
        "- TraceableClaim cross-field invariants (each violation is a schema "
        "validation error, so verify every one before returning JSON): a "
        "provider can never appear in both supporting_models and "
        "disputing_models for the same claim; every provider named in "
        "support[] must also appear in supporting_models; every provider "
        "named in dispute[] must also appear in disputing_models; if "
        "assessment.status is 'supported', support[] must contain at least "
        "one real excerpt copied from that provider's response — never set "
        "status 'supported' based on supporting_models alone without a "
        "matching support excerpt; if assessment.status is 'disputed', "
        "disputing_models must contain at least one provider.\n"
        "- Use stable claim IDs such as claim_1, claim_2.\n"
        "- A shared fact is a factual claim supported by at least two supplied "
        "providers with one exact response excerpt from each.\n"
        "- Agreements require two distinct supplied providers.\n"
        "- If only one usable provider is supplied, agreements must be empty, "
        "confidence.factors.model_agreement must be low, and the answer must "
        "clearly state that consensus is limited.\n"
        "- Agreements describe shared interpretations or conclusions; do not "
        "repeat a shared factual claim as an agreement.\n"
        "- Do not manufacture disagreements.\n"
        "- trusted_conclusion.disagreements[] and trusted_conclusion."
        "claim_disagreements[] are two different structures with different "
        "fields. Never mix fields between them.\n"
        "- In trusted_conclusion.disagreements[]: each entry in positions[] "
        "uses the field 'model' (never 'provider'); evidence_claim_ids "
        "belongs inside each position; referee_assessment is required on "
        "the disagreement itself and must state each provider's specific "
        "position and the missing_information that could resolve it. Never "
        "put disagreement_type, impact_on_verdict or referee_resolution "
        "anywhere in trusted_conclusion.disagreements[] — those fields "
        "belong only to claim_disagreements.\n"
        "- In trusted_conclusion.claim_disagreements[]: each entry in "
        "positions[] uses the field 'provider' (never 'model'); claim_ids "
        "must reference claim_matrix, never evidence_claim_ids; the "
        "disagreement itself carries disagreement_type, impact_on_verdict "
        "and referee_resolution. Never put evidence_claim_ids inside "
        "claim_disagreements[].positions[] and never put "
        "referee_assessment anywhere in trusted_conclusion."
        "claim_disagreements[] — those fields belong only to "
        "disagreements. Use claim_disagreements only for genuinely "
        "incompatible positions, never for style, additional examples, "
        "omission, or cautious wording alone.\n"
        "- support[].response_excerpt and dispute[].response_excerpt (and "
        "response_reference start_hint/end_hint, when present) must each be "
        "a short, CONTIGUOUS, character-for-character substring copied "
        "directly from that provider's response field above. Before "
        "writing one, locate the exact span in the response text and copy "
        "it unchanged. Never: translate it (even though every other "
        "field is written in the target language, excerpts stay in the "
        "response's original language); paraphrase or summarize it; add "
        "an ellipsis or otherwise skip words from the middle; join two "
        "separate spans of the response into one excerpt; fix grammar, "
        "spelling or capitalization; change any punctuation, quotation "
        "mark, or dash character; strip Markdown if doing so would alter "
        "the substring; or add or remove any word. If no single "
        "contiguous span expresses the point cleanly, pick a shorter span "
        "that IS an exact contiguous substring rather than editing one.\n"
        "- For a disputed claim, put exact excerpts supporting the claim in "
        "support and exact excerpts opposing it in dispute.\n"
        "- provider_response_id must exactly match the supplied ID.\n"
        "- supporting, disputing and originating models may use only: "
        f"{', '.join(allowed_providers)}.\n"
        f"- claim_analysis.execution_mode must be {execution_mode}.\n"
        "- Only use citation IDs supplied in available_citations, and only "
        "when the provider explicitly connects that citation to the claim.\n"
        "- Do not create URLs, citation IDs, source titles or publications.\n"
        "- Provider citations are unverified. Never claim independent "
        "verification or turn a citation into proof of truth.\n"
        "- If no citations are supplied, every citation_ids array must be empty "
        "and referee_reasoning must explicitly say that the provider responses "
        "contain no usable source references.\n"
        "- FAILED providers are absent and cannot support or dispute claims.\n"
        "- supporting_claim_ids, disputing_claim_ids, position "
        "evidence_claim_ids, evidence_claim_ids and unsupported_claim_ids "
        "must reference claim IDs in claim_analysis.\n"
        "- strongest_evidence must add evidentiary context, not repeat the "
        "same wording already used in agreements.\n"
        "- Be concise and non-redundant across the whole response. Do not "
        "restate information already encoded in structured fields (provider "
        "positions, statuses, models) unless needed to make the final "
        "answer or a specific assessment understandable on its own.\n"
        "- claim_matrix[].referee_assessment and Disagreement."
        "referee_assessment must be concise: a short, direct statement, "
        "not a restated narrative.\n"
        "- claim_matrix[].provider_positions[].summary must not repeat the "
        "wording of that same claim's claim_analysis.claims[].assessment."
        "reason; state only what is specific to that provider's position.\n"
        "- agreements and disagreements must not restate each other, and "
        "must not repeat claim-level detail already captured in "
        "claim_matrix; keep each to the minimum needed to convey the "
        "point.\n"
        "- This conciseness requirement never applies to final_answer: "
        "final_answer must stay complete, specific and readable -- never "
        "shorten it into a telegraphic or incomplete answer.\n"
        "- This conciseness requirement never shortens support[]/dispute[] "
        "response_excerpt below what the exact-substring rules above "
        "already require.\n"
        "- referee_reasoning must explain how agreements, disagreements, "
        "evidence quality and uncertainty lead to the final answer.\n"
        "- Confidence is high, medium or low only; never output a confidence "
        "percentage.\n"
        "- State uncertainty when the evidence is limited.\n"
        "- Empty optional sections must be empty arrays."
    )


def _human_label_list(labels: list[str]) -> str:
    clean = [label for label in labels if label]
    if not clean:
        return "none"
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return f"{', '.join(clean[:-1])}, and {clean[-1]}"


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

    payload = _normalize_bundle_provider_aliases(payload)
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
    _validate_conclusion_claim_references(
        conclusion,
        analysis,
        answers,
        citations,
    )
    associated_citations = associate_citations_with_claims(citations, analysis)
    try:
        conclusion = _enrich_conclusion(
            conclusion,
            analysis,
            associated_citations,
            answers,
        )
    except Exception as enrichment_error:
        # Diagnostic-only provenance tag (perf/synthesizer-next-bottleneck-
        # diagnostics): identifies failures from this specific, local
        # TrustedConclusionV21 re-validation step, which is otherwise
        # indistinguishable from a bundle/conclusion schema failure in
        # _log_parse_failure. Never changes the exception itself.
        enrichment_error._diagnostic_stage = "enrich_conclusion"  # noqa: SLF001
        raise
    return {
        "conclusion": conclusion,
        "claim_analysis": analysis,
        "claim_analysis_status": "SUCCESS",
        "claim_analysis_error": None,
        "citations": associated_citations,
    }


def _validate_conclusion_claim_references(
    conclusion: TrustedConclusionV2,
    analysis: ClaimAnalysisV3,
    answers: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> None:
    known = {claim.id for claim in analysis.claims}
    references: list[str] = []
    for agreement in conclusion.agreements:
        references.extend(agreement.supporting_claim_ids)
    for disagreement in conclusion.disagreements:
        references.extend(disagreement.disputing_claim_ids)
        for position in disagreement.positions:
            references.extend(position.evidence_claim_ids)
    for evidence in conclusion.strongest_evidence:
        references.extend(evidence.evidence_claim_ids)
    for unsupported in conclusion.unsupported_claims:
        references.extend(unsupported.unsupported_claim_ids)
    references.extend(item.claim_id for item in conclusion.claim_matrix)
    for agreement in conclusion.claim_agreements:
        references.extend(agreement.claim_ids)
    for disagreement in conclusion.claim_disagreements:
        references.extend(disagreement.claim_ids)
    for contribution in conclusion.exclusive_contributions:
        references.extend(contribution.related_claim_ids)
    unknown = sorted(set(references) - known)
    if unknown:
        raise ValueError(
            "Trusted Conclusion references unknown claim IDs: "
            + ", ".join(unknown)
        )
    known_evidence_refs = {
        str(
            answer.get("provider_response_id")
            or answer.get("provider_key")
            or ""
        ).strip()
        for answer in answers
    } | {
        str(citation.get("id") or "").strip()
        for citation in citations
    }
    known_evidence_refs.discard("")
    unknown_evidence_refs = sorted(
        {
            reference
            for item in conclusion.claim_matrix
            for position in item.provider_positions
            for reference in position.evidence_refs
            if reference not in known_evidence_refs
        }
    )
    if unknown_evidence_refs:
        raise ValueError(
            "Claim matrix references unknown evidence IDs: "
            + ", ".join(unknown_evidence_refs)
        )
    claim_by_id = {claim.id: claim for claim in analysis.claims}
    for disagreement in conclusion.disagreements:
        for position in disagreement.positions:
            for claim_id in position.evidence_claim_ids:
                claim = claim_by_id[claim_id]
                providers = (
                    set(claim.originating_models)
                    | set(claim.supporting_models)
                    | set(claim.disputing_models)
                )
                if position.model not in providers:
                    raise ValueError(
                        "Disagreement position references evidence from "
                        "another provider"
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
            for position in item.get("positions", []):
                position["evidence_claim_ids"] = []
        for item in candidate.get("strongest_evidence", []):
            item["evidence_claim_ids"] = []
        for item in candidate.get("unsupported_claims", []):
            item["unsupported_claim_ids"] = []
        discarded = []
        for field in (
            "claim_matrix",
            "claim_agreements",
            "claim_disagreements",
            "exclusive_contributions",
            "decisive_factors",
        ):
            if candidate.get(field):
                discarded.append(field)
            candidate[field] = []
        if discarded:
            log.warning(
                "Discarded malformed optional structured sections during "
                "conclusion salvage: %s",
                ", ".join(discarded),
            )
        return parse_structured_conclusion(candidate, allowed_providers)
    except Exception:
        return None


def _enrich_conclusion(
    conclusion: TrustedConclusionV2,
    analysis: ClaimAnalysisV3,
    citations: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> TrustedConclusionV21:
    """Build the 2.1 evidence view only from already validated local data.

    The synthesizer does not get to create source-summary records, provider
    scores or excerpts. Those values are derived here from exact provider
    responses, validated claims and deterministic citation extraction.
    """
    source_summary = [_source_summary_item(item) for item in citations]
    known_source_ids = {item["id"] for item in source_summary}

    key_findings = []
    for claim in analysis.claims:
        supporters = list(dict.fromkeys(claim.supporting_models))
        dissenters = list(dict.fromkeys(claim.disputing_models))
        finding_status = _finding_status(claim.assessment.status)
        source_references = [
            citation_id
            for citation_id in claim.citation_ids
            if citation_id in known_source_ids
        ]
        relevant_excerpts = [
            {
                "provider": excerpt.provider,
                "text": excerpt.response_excerpt,
                "stance": stance,
                "provider_response_id": (
                    excerpt.response_reference.provider_response_id
                ),
            }
            for stance, excerpts in (
                ("support", claim.support),
                ("dissent", claim.dispute),
            )
            for excerpt in excerpts
        ]
        key_findings.append(
            {
                "id": claim.id,
                "claim": claim.text,
                "status": finding_status,
                "explanation": claim.assessment.reason,
                "supporting_providers": supporters,
                "dissenting_providers": dissenters,
                "evidence_strength": _evidence_strength(
                    supporters,
                    dissenters,
                    claim.assessment.status,
                ),
                "source_references": source_references,
                "relevant_excerpts": relevant_excerpts,
            }
        )
    if not key_findings:
        key_findings = _derive_key_findings_from_conclusion(conclusion)

    provider_assessment = _provider_assessments(
        analysis,
        citations,
        answers,
    )
    strongest_shared = next(
        (
            item.model_dump()
            for item in conclusion.strongest_evidence
            if len(set(item.supporting_models)) >= 2
        ),
        None,
    )
    payload = conclusion.model_dump()
    phase_b = _phase_b_fields_from_analysis(
        conclusion,
        analysis,
        answers,
    )
    for field, value in phase_b.items():
        if not payload.get(field):
            payload[field] = value
    payload.update(
        {
            "schema_version": "2.1",
            "final_verdict": conclusion.final_answer,
            "confidence_reason": conclusion.confidence.reason,
            "key_findings": key_findings,
            "uncertainties": [
                item.model_dump()
                for item in conclusion.remaining_uncertainties
            ],
            "strongest_shared_evidence": strongest_shared,
            "what_could_change": list(
                conclusion.what_could_change_the_verdict
            ),
            "provider_assessment": provider_assessment,
            "source_summary": source_summary,
        }
    )
    return TrustedConclusionV21.model_validate(payload)


def _enrich_conclusion_without_claim_analysis(
    conclusion: TrustedConclusionV2,
    citations: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    execution_mode: str,
) -> TrustedConclusionV2:
    """Preserve existing structured evidence after claim validation fails.

    This fallback copies only already validated conclusion text and provider
    keys. It intentionally cannot create excerpts, source links or new claims.
    """
    key_findings = _derive_key_findings_from_conclusion(conclusion)
    if not key_findings:
        return conclusion
    source_summary = [_source_summary_item(item) for item in citations]
    empty_analysis = ClaimAnalysisV3(
        schema_version="3.0",
        execution_mode="DEMO" if execution_mode == "DEMO" else "LIVE",
        claims=[],
    )
    payload = conclusion.model_dump()
    phase_b = _phase_b_fields_from_findings(
        conclusion,
        key_findings,
        answers,
    )
    for field, value in phase_b.items():
        if not payload.get(field):
            payload[field] = value
    payload.update(
        {
            "schema_version": "2.1",
            "final_verdict": conclusion.final_answer,
            "confidence_reason": conclusion.confidence.reason,
            "key_findings": key_findings,
            "uncertainties": [
                item.model_dump()
                for item in conclusion.remaining_uncertainties
            ],
            "strongest_shared_evidence": next(
                (
                    item.model_dump()
                    for item in conclusion.strongest_evidence
                    if len(set(item.supporting_models)) >= 2
                ),
                None,
            ),
            "what_could_change": list(
                conclusion.what_could_change_the_verdict
            ),
            "provider_assessment": _provider_assessments(
                empty_analysis,
                citations,
                answers,
            ),
            "source_summary": source_summary,
        }
    )
    return TrustedConclusionV21.model_validate(payload)


def _phase_b_fields_from_analysis(
    conclusion: TrustedConclusionV2,
    analysis: ClaimAnalysisV3,
    answers: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Derive a conservative matrix from already validated claim evidence."""
    participants = _phase_b_participants(answers)
    important_ids = {
        claim_id
        for evidence in conclusion.strongest_evidence
        for claim_id in evidence.evidence_claim_ids
    }
    referenced_ids = {
        claim_id
        for agreement in conclusion.agreements
        for claim_id in agreement.supporting_claim_ids
    } | {
        claim_id
        for disagreement in conclusion.disagreements
        for claim_id in disagreement.disputing_claim_ids
    }

    matrix: list[dict[str, Any]] = []
    for claim in analysis.claims:
        excerpts_by_provider: dict[str, list[Any]] = {}
        for excerpt in list(claim.support) + list(claim.dispute):
            excerpts_by_provider.setdefault(excerpt.provider, []).append(excerpt)
        positions = []
        for provider, display_name in participants:
            if provider in claim.supporting_models:
                position = "supports"
            elif provider in claim.disputing_models:
                position = "contradicts"
            elif provider in claim.originating_models:
                position = "uncertain"
            else:
                position = "not_mentioned"
            excerpts = excerpts_by_provider.get(provider, [])
            summary = (
                excerpts[0].response_excerpt
                if excerpts
                else (
                    claim.assessment.reason
                    if position == "uncertain"
                    else ""
                )
            )
            evidence_refs = list(
                dict.fromkeys(
                    excerpt.response_reference.provider_response_id
                    for excerpt in excerpts
                )
            )
            positions.append(
                {
                    "provider": provider,
                    "display_name": display_name,
                    "position": position,
                    "summary": summary,
                    "evidence_refs": evidence_refs,
                    "confidence": (
                        "high"
                        if excerpts and position == "supports"
                        else "medium"
                        if excerpts
                        else "low"
                    ),
                }
            )
        if claim.id in important_ids:
            importance = "high"
        elif claim.id in referenced_ids:
            importance = "medium"
        elif claim.assessment.status in ("weak", "unsupported"):
            importance = "low"
        else:
            importance = "medium"
        matrix.append(
            {
                "claim_id": claim.id,
                "claim": claim.text,
                "importance": importance,
                "provider_positions": positions,
                "agreement_level": _phase_b_agreement_level(positions),
                "referee_assessment": claim.assessment.reason,
                "evidence_limitations": [],
            }
        )
    return _phase_b_sections(conclusion, matrix)


def _phase_b_fields_from_findings(
    conclusion: TrustedConclusionV2,
    findings: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build only the minimum matrix supported by legacy structured fields."""
    participants = _phase_b_participants(answers)
    matrix = []
    for finding in findings:
        supporters = set(finding.get("supporting_providers") or [])
        dissenters = set(finding.get("dissenting_providers") or [])
        excerpts = finding.get("relevant_excerpts") or []
        positions = []
        for provider, display_name in participants:
            if provider in supporters:
                position = "supports"
            elif provider in dissenters:
                position = "contradicts"
            else:
                position = "not_mentioned"
            matching = [
                excerpt
                for excerpt in excerpts
                if excerpt.get("provider") == provider
            ]
            positions.append(
                {
                    "provider": provider,
                    "display_name": display_name,
                    "position": position,
                    "summary": (
                        matching[0].get("text", "")
                        if matching
                        else (
                            finding.get("explanation", "")
                            if position != "not_mentioned"
                            else ""
                        )
                    ),
                    "evidence_refs": list(
                        dict.fromkeys(
                            excerpt.get("provider_response_id", "")
                            for excerpt in matching
                            if excerpt.get("provider_response_id")
                        )
                    ),
                    "confidence": "medium" if matching else "low",
                }
            )
        matrix.append(
            {
                "claim_id": finding["id"],
                "claim": finding["claim"],
                "importance": (
                    "high"
                    if finding.get("evidence_strength") == "strong"
                    else "medium"
                    if finding.get("evidence_strength") == "moderate"
                    else "low"
                ),
                "provider_positions": positions,
                "agreement_level": _phase_b_agreement_level(positions),
                "referee_assessment": finding.get("explanation") or finding["claim"],
                "evidence_limitations": [],
            }
        )
    return _phase_b_sections(conclusion, matrix)


def _phase_b_sections(
    conclusion: TrustedConclusionV2,
    matrix: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    agreements = []
    disagreements = []
    exclusive_contributions = []
    for item in matrix:
        supporters = [
            position["provider"]
            for position in item["provider_positions"]
            if position["position"] in ("supports", "partially_supports")
        ]
        opponents = [
            position["provider"]
            for position in item["provider_positions"]
            if position["position"] == "contradicts"
        ]
        if item["agreement_level"] in ("unanimous", "strong_consensus"):
            agreements.append(
                {
                    "topic": item["claim"],
                    "claim_ids": [item["claim_id"]],
                    "providers": supporters,
                    "strength": (
                        "high"
                        if item["agreement_level"] == "unanimous"
                        else "medium"
                    ),
                    "explanation": item["referee_assessment"],
                }
            )
        elif item["agreement_level"] == "disputed":
            positions = [
                {
                    "provider": position["provider"],
                    "position": position["summary"],
                }
                for position in item["provider_positions"]
                if position["position"]
                in ("supports", "partially_supports", "contradicts")
                and position["summary"]
            ]
            if len({position["provider"] for position in positions}) >= 2:
                disagreements.append(
                    {
                        "topic": item["claim"],
                        "claim_ids": [item["claim_id"]],
                        "positions": positions,
                        "disagreement_type": "interpretation",
                        "impact_on_verdict": (
                            "high"
                            if item["importance"] == "high"
                            else "medium"
                        ),
                        "referee_resolution": item["referee_assessment"],
                    }
                )
        involved = list(dict.fromkeys(supporters + opponents))
        if len(involved) == 1:
            provider = involved[0]
            provider_position = next(
                position
                for position in item["provider_positions"]
                if position["provider"] == provider
            )
            exclusive_contributions.append(
                {
                    "provider": provider,
                    "contribution": item["claim"],
                    "related_claim_ids": [item["claim_id"]],
                    "verification_status": (
                        "supported_within_response"
                        if provider_position["evidence_refs"]
                        and provider_position["position"] == "supports"
                        else "contradicted"
                        if provider_position["position"] == "contradicts"
                        else "unverified"
                    ),
                    "referee_note": item["referee_assessment"],
                }
            )

    matrix_by_id = {item["claim_id"]: item for item in matrix}
    decisive_factors = []
    for evidence in conclusion.strongest_evidence:
        linked = [
            matrix_by_id[claim_id]
            for claim_id in evidence.evidence_claim_ids
            if claim_id in matrix_by_id
        ]
        if not linked:
            continue
        opposed_by = list(
            dict.fromkeys(
                position["provider"]
                for item in linked
                for position in item["provider_positions"]
                if position["position"] == "contradicts"
            )
        )
        decisive_factors.append(
            {
                "factor": evidence.claim,
                "supported_by": list(dict.fromkeys(evidence.supporting_models)),
                "opposed_by": opposed_by,
                "weight": (
                    "high"
                    if any(item["importance"] == "high" for item in linked)
                    else "medium"
                ),
                "explanation": evidence.description,
            }
        )
    return {
        "claim_matrix": matrix,
        "claim_agreements": agreements,
        "claim_disagreements": disagreements,
        "exclusive_contributions": exclusive_contributions,
        "decisive_factors": decisive_factors,
    }


def _phase_b_participants(
    answers: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    participants = []
    seen = set()
    for answer in answers:
        provider = str(answer.get("provider_key") or "").strip().lower()
        if not provider or provider in seen:
            continue
        seen.add(provider)
        participants.append(
            (
                provider,
                str(answer.get("label") or provider).strip(),
            )
        )
    return participants


def _phase_b_agreement_level(
    positions: list[dict[str, Any]],
) -> str:
    values = [position["position"] for position in positions]
    if len(values) >= 2 and all(value == "supports" for value in values):
        return "unanimous"
    supporters = values.count("supports")
    if supporters >= 2 and "contradicts" not in values:
        return "strong_consensus"
    if "contradicts" in values and any(
        value in ("supports", "partially_supports")
        for value in values
    ):
        return "disputed"
    if supporters or "partially_supports" in values:
        return "partial_consensus"
    return "unresolved"


def _derive_key_findings_from_conclusion(
    conclusion: TrustedConclusionV2,
) -> list[dict[str, Any]]:
    """Copy existing agreement/evidence claims into conservative findings."""
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates: list[tuple[str, str, list[str], str]] = []
    candidates.extend(
        (
            agreement.claim,
            agreement.reason,
            list(agreement.supporting_models),
            agreement.strength,
        )
        for agreement in conclusion.agreements
    )
    candidates.extend(
        (
            evidence.claim,
            evidence.description,
            list(evidence.supporting_models),
            _evidence_strength(
                list(evidence.supporting_models),
                [],
                "supported",
            ),
        )
        for evidence in conclusion.strongest_evidence
    )
    for claim, explanation, supporters, strength in candidates:
        identity = re.sub(r"\s+", " ", claim).strip().casefold()
        if not identity or identity in seen or not supporters:
            continue
        seen.add(identity)
        findings.append(
            {
                "id": f"claim_derived_{len(findings) + 1}",
                "claim": claim,
                "status": "probable" if len(set(supporters)) >= 2 else "uncertain",
                "explanation": explanation,
                "supporting_providers": list(dict.fromkeys(supporters)),
                "dissenting_providers": [],
                "evidence_strength": strength,
                "source_references": [],
                "relevant_excerpts": [],
            }
        )
    return findings


def _source_summary_item(citation: dict[str, Any]) -> dict[str, Any]:
    declared_by = list(dict.fromkeys(citation.get("declared_by_models") or []))
    citation_status = str(citation.get("verification_status") or "")
    if citation_status == "invalid_url":
        status = "malformed"
        safe_url = None
    elif len(declared_by) >= 2:
        status = "shared_by_multiple_models"
        safe_url = citation.get("url")
    elif citation.get("url") or citation.get("title"):
        status = "provided_by_model"
        safe_url = citation.get("url")
    else:
        status = "unverified"
        safe_url = None
    return {
        "id": citation["id"],
        "title": citation.get("title"),
        "url": safe_url,
        "publisher": citation.get("domain"),
        "domain": citation.get("domain"),
        "cited_by": declared_by,
        "supports_claim_ids": list(
            dict.fromkeys(citation.get("associated_claim_ids") or [])
        ),
        "verification_status": status,
    }


def _finding_status(value: str) -> str:
    # "verified" is intentionally reserved for a future independent
    # verification layer. Agreement between providers is not external proof.
    return {
        "supported": "probable",
        "disputed": "disputed",
        "weak": "uncertain",
        "unsupported": "unsupported",
    }.get(value, "uncertain")


def _evidence_strength(
    supporters: list[str],
    dissenters: list[str],
    assessment_status: str,
) -> str:
    if assessment_status in ("weak", "unsupported") or dissenters:
        return "weak"
    if len(set(supporters)) >= 2:
        return "strong"
    if supporters:
        return "moderate"
    return "weak"


def _provider_assessments(
    analysis: ClaimAnalysisV3,
    citations: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assessments = []
    for answer in answers:
        provider = str(answer.get("provider_key") or "").strip().lower()
        if not provider:
            continue
        contributions: list[str] = []
        weaknesses: list[str] = []
        related_claims = []
        for claim in analysis.claims:
            involved = provider in (
                set(claim.originating_models)
                | set(claim.supporting_models)
                | set(claim.disputing_models)
            )
            if not involved:
                continue
            related_claims.append(claim)
            if (
                provider in claim.supporting_models
                and claim.assessment.status == "supported"
            ):
                contributions.append(claim.text)
            if (
                provider in claim.originating_models
                and claim.assessment.status in ("weak", "unsupported")
            ):
                weaknesses.append(claim.text)
            elif (
                provider in claim.supporting_models
                and claim.assessment.status == "disputed"
            ):
                weaknesses.append(claim.text)
        if not related_claims:
            coherence = "not_assessed"
        elif weaknesses:
            coherence = "medium"
        else:
            coherence = "high"
        usable_citations = [
            citation["id"]
            for citation in citations
            if provider in (citation.get("declared_by_models") or [])
            and citation.get("verification_status") != "invalid_url"
        ]
        assessments.append(
            {
                "provider": provider,
                "useful_contributions": list(dict.fromkeys(contributions)),
                "weaknesses": list(dict.fromkeys(weaknesses)),
                # No independent source verification happens in this phase.
                "perceived_accuracy": "not_assessed",
                "coherence": coherence,
                "usable_citation_ids": list(dict.fromkeys(usable_citations)),
            }
        )
    return assessments


def _normalize_bundle_provider_aliases(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Normalize provider labels only in fields governed by ProviderKey."""
    normalized = json.loads(json.dumps(payload))
    conclusion = normalized.get("trusted_conclusion")
    if isinstance(conclusion, dict):
        for agreement in conclusion.get("agreements") or []:
            _normalize_provider_list(agreement, "supporting_models")
        for disagreement in conclusion.get("disagreements") or []:
            for position in disagreement.get("positions") or []:
                _normalize_provider_value(position, "model")
        for evidence in conclusion.get("strongest_evidence") or []:
            _normalize_provider_list(evidence, "supporting_models")
        for claim in conclusion.get("unsupported_claims") or []:
            _normalize_provider_list(claim, "originating_models")
        for matrix_item in conclusion.get("claim_matrix") or []:
            for position in matrix_item.get("provider_positions") or []:
                _normalize_provider_value(position, "provider")
        for agreement in conclusion.get("claim_agreements") or []:
            _normalize_provider_list(agreement, "providers")
        for disagreement in conclusion.get("claim_disagreements") or []:
            for position in disagreement.get("positions") or []:
                _normalize_provider_value(position, "provider")
        for contribution in conclusion.get("exclusive_contributions") or []:
            _normalize_provider_value(contribution, "provider")
        for factor in conclusion.get("decisive_factors") or []:
            _normalize_provider_list(factor, "supported_by")
            _normalize_provider_list(factor, "opposed_by")

    analysis = normalized.get("claim_analysis")
    if isinstance(analysis, dict):
        for claim in analysis.get("claims") or []:
            for field in (
                "originating_models",
                "supporting_models",
                "disputing_models",
            ):
                _normalize_provider_list(claim, field)
            for excerpt in (
                list(claim.get("support") or [])
                + list(claim.get("dispute") or [])
            ):
                _normalize_provider_value(excerpt, "provider")
    return normalized


def _normalize_provider_list(container: Any, key: str) -> None:
    if not isinstance(container, dict) or not isinstance(container.get(key), list):
        return
    container[key] = [
        _normalized_provider_or_original(value)
        for value in container[key]
    ]


def _normalize_provider_value(container: Any, key: str) -> None:
    if not isinstance(container, dict) or key not in container:
        return
    container[key] = _normalized_provider_or_original(container.get(key))


def _normalized_provider_or_original(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = _PROVIDER_ALIASES.get(value.strip().casefold())
    return normalized or value


def _trace_enabled() -> bool:
    return (
        os.environ.get(TRACE_CONCLUSION_ENV, "").strip().casefold()
        in _TRUE_VALUES
    )


def _trace_raw_payload(stage: str, raw: str) -> None:
    if not _trace_enabled():
        return
    try:
        payload = json.loads(_extract_json_object(raw))
    except Exception as exc:
        _trace_event(
            stage,
            {
                "json_valid": False,
                "error_type": type(exc).__name__,
            },
        )
        return

    conclusion = payload.get("trusted_conclusion")
    analysis = payload.get("claim_analysis")
    conclusion = conclusion if isinstance(conclusion, dict) else {}
    analysis = analysis if isinstance(analysis, dict) else {}
    raw_claims = analysis.get("claims")
    raw_findings = conclusion.get("key_findings")
    normalized = _normalize_bundle_provider_aliases(payload)
    _trace_event(
        stage,
        {
            "json_valid": True,
            "raw_keys": sorted(str(key) for key in payload),
            "trusted_conclusion_keys": sorted(
                str(key) for key in conclusion
            ),
            "claim_analysis_keys": sorted(str(key) for key in analysis),
            "schema_version": conclusion.get("schema_version"),
            "agreements_count": _safe_list_count(
                conclusion.get("agreements")
            ),
            "strongest_evidence_count": _safe_list_count(
                conclusion.get("strongest_evidence")
            ),
            "claim_matrix_count": _safe_list_count(
                conclusion.get("claim_matrix")
            ),
            "claim_agreements_count": _safe_list_count(
                conclusion.get("claim_agreements")
            ),
            "claim_disagreements_count": _safe_list_count(
                conclusion.get("claim_disagreements")
            ),
            "raw_key_findings_count": _safe_list_count(raw_findings),
            "claim_count": _safe_list_count(raw_claims),
            "normalized_providers": _normalized_provider_names(normalized),
        },
    )


def _safe_diagnostic_value(value: Any) -> Optional[str]:
    """Return a bounded, single-line identifier suitable for diagnostics."""
    if value is None:
        return None
    clean = _SAFE_DIAGNOSTIC_VALUE_RE.sub("_", str(value).strip())[:200]
    return clean or None


@lru_cache(maxsize=1)
def _known_validation_fields() -> set[str]:
    """Collect schema property names so arbitrary extra keys are never logged."""
    fields: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                fields.update(str(key) for key in properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(SynthesisBundleV3.model_json_schema())
    visit(TrustedConclusionV21.model_json_schema())
    return fields


def _safe_validation_location(location: Any) -> str:
    known_fields = _known_validation_fields()
    parts: list[str] = []
    for part in location or []:
        if isinstance(part, int):
            parts.append(str(part))
        elif str(part) in known_fields:
            parts.append(str(part))
        else:
            parts.append("<unknown_field>")
    return ".".join(parts) or "<root>"


def _validation_error_summary(error: ValidationError) -> dict[str, Any]:
    raw_errors = error.errors()
    errors = []
    for item in raw_errors[:_MAX_VALIDATION_ERRORS_LOGGED]:
        error_type = _safe_diagnostic_value(item.get("type")) or "validation_error"
        errors.append(
            {
                "location": _safe_validation_location(item.get("loc")),
                "type": error_type,
                "code": f"pydantic.{error_type}",
            }
        )
    return {"error_count": len(raw_errors), "errors": errors}


# Diagnostic-only classification for post-Pydantic ValueError raises (perf/
# synthesizer-next-bottleneck-diagnostics, purely additive): every raw
# ValueError below this point in the parsing pipeline is raised *after* the
# corresponding model_validate() already succeeded, so Pydantic's own
# location/type diagnostics (see _validation_error_summary above) do not
# apply to them. Each tuple matches a stable, hard-coded message prefix from
# a known raise site -- never the exception content itself, which may embed
# LLM-generated claim/evidence IDs that carry no schema pattern constraint
# and could otherwise leak fragments of provider or user content into logs.
# (stage_name, diagnostic_code, message_prefix)
_POST_VALIDATION_ERROR_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "parse_structured_conclusion",
        "provider_not_participating",
        "Conclusion references providers outside the current execution",
    ),
    (
        "parse_structured_conclusion",
        "claim_matrix_missing_participating_provider",
        "claim matrix must contain one position for every "
        "participating provider",
    ),
    (
        "parse_structured_conclusion",
        "single_provider_agreement_not_low",
        "a single-provider conclusion must report low model agreement",
    ),
    (
        "validate_claim_analysis",
        "execution_mode_mismatch",
        "claim analysis execution mode does not match comparison",
    ),
    (
        "validate_claim_analysis",
        "execution_mode_mismatch",
        "claim evidence crosses LIVE and DEMO execution modes",
    ),
    (
        "validate_claim_analysis",
        "provider_failed",
        "claim references a FAILED or absent provider",
    ),
    (
        "validate_claim_analysis",
        "claim_excerpt_not_in_provider_response",
        "claim dispute excerpt is not present in provider response",
    ),
    (
        "validate_claim_analysis",
        "claim_excerpt_not_in_provider_response",
        "claim excerpt is not present in provider response",
    ),
    (
        "validate_claim_analysis",
        "provider_response_id_mismatch",
        "claim dispute response reference does not match provider",
    ),
    (
        "validate_claim_analysis",
        "provider_response_id_mismatch",
        "claim response reference does not match provider",
    ),
    (
        "validate_claim_analysis",
        "hint_not_in_provider_response",
        "claim dispute response hint is not present in response",
    ),
    (
        "validate_claim_analysis",
        "hint_not_in_provider_response",
        "claim response hint is not present in response",
    ),
    (
        "validate_claim_analysis",
        "unknown_citation_reference",
        "claim references an unknown citation",
    ),
    (
        "validate_claim_analysis",
        "citation_provenance_mismatch",
        "citation provenance does not match claim providers",
    ),
    (
        "validate_conclusion_claim_references",
        "unknown_claim_reference",
        "Trusted Conclusion references unknown claim IDs",
    ),
    (
        "validate_conclusion_claim_references",
        "unknown_evidence_reference",
        "Claim matrix references unknown evidence IDs",
    ),
    (
        "validate_conclusion_claim_references",
        "disagreement_evidence_provider_mismatch",
        "Disagreement position references evidence from another provider",
    ),
)


def _classify_post_validation_error(error: Exception) -> tuple[str, str]:
    """Classify a post-Pydantic parse failure into a stable, safe code.

    Matches only against the hard-coded message prefixes above -- never
    against the exception message itself. A ValidationError never reaches
    here (see _log_parse_failure); it is always a raw ValueError raised by
    one of the business-rule checks in conclusion_schema.py,
    traceability_schema.py or _validate_conclusion_claim_references, or an
    unrelated exception (e.g. malformed JSON) that this classifier cannot
    attribute to a specific check.
    """
    message = str(error) if isinstance(error, ValueError) else ""
    for stage, code, prefix in _POST_VALIDATION_ERROR_PATTERNS:
        if message.startswith(prefix):
            return code, stage
    return "other_post_pydantic_validation_error", "unknown"


# Diagnostic-aware repair instructions (fix/synthesizer-exact-excerpts,
# purely additive): keyed by the same stable diagnostic_code computed by
# _classify_post_validation_error above. Selected only by that code -- never
# by str(error) -- so no exception content, excerpt, or provider text can
# reach this text. Deliberately narrow: only failure classes where a short,
# unambiguous, non-content-bearing correction is possible.
_REPAIR_DIAGNOSTIC_INSTRUCTIONS: dict[str, str] = {
    "claim_excerpt_not_in_provider_response": (
        "One or more support/dispute excerpts are not exact substrings of "
        "the declared provider responses. Replace each invalid excerpt "
        "with a short, contiguous, character-for-character substring "
        "copied directly from the corresponding provider response. Do "
        "not translate, paraphrase, merge, shorten with ellipses, "
        "normalize punctuation, or rewrite it."
    ),
    "hint_not_in_provider_response": (
        "One or more response_reference start_hint/end_hint values are "
        "not exact substrings of the declared provider response. Replace "
        "each invalid hint with a short, contiguous, character-for-"
        "character substring copied directly from that provider "
        "response, or omit the hint."
    ),
    "provider_response_id_mismatch": (
        "One or more response_reference.provider_response_id values do "
        "not match the provider_response_id supplied for that provider in "
        "provider_responses. Set each provider_response_id to exactly the "
        "value supplied for that provider."
    ),
}


def _repair_diagnostic_instruction(error: Exception) -> str:
    """Return a targeted repair instruction for a known diagnostic_code.

    Returns "" for any other code (including other_post_pydantic_
    validation_error and ValidationError), leaving the repair system
    prompt exactly as it was before this patch.
    """
    diagnostic_code, _ = _classify_post_validation_error(error)
    return _REPAIR_DIAGNOSTIC_INSTRUCTIONS.get(diagnostic_code, "")


def _log_parse_failure(
    query_id: str,
    stage: str,
    model: str,
    error: Exception,
) -> None:
    safe_query_id = _safe_diagnostic_value(query_id) or "unknown"
    safe_model = _safe_diagnostic_value(model) or "unknown"
    if isinstance(error, ValidationError):
        summary = _validation_error_summary(error)
        log.warning(
            "synthesis_validation_error query_id=%s stage=%s "
            "error_count=%d model=%s errors=%s",
            safe_query_id,
            stage,
            summary["error_count"],
            safe_model,
            json.dumps(summary["errors"], separators=(",", ":")),
        )
        if getattr(error, "_diagnostic_stage", None) == "enrich_conclusion":
            log.warning(
                "synthesis_post_validation_error query_id=%s stage=%s "
                "validation_stage=%s diagnostic_code=%s error_type=%s",
                safe_query_id,
                stage,
                "enrich_conclusion",
                "conclusion_enrichment_validation_failed",
                _safe_diagnostic_value(type(error).__name__) or "Exception",
            )
        return
    log.warning(
        "synthesis_parse_failed query_id=%s stage=%s error_type=%s model=%s",
        safe_query_id,
        stage,
        _safe_diagnostic_value(type(error).__name__) or "Exception",
        safe_model,
    )
    diagnostic_code, validation_stage = _classify_post_validation_error(error)
    log.warning(
        "synthesis_post_validation_error query_id=%s stage=%s "
        "validation_stage=%s diagnostic_code=%s error_type=%s",
        safe_query_id,
        stage,
        validation_stage,
        diagnostic_code,
        _safe_diagnostic_value(type(error).__name__) or "Exception",
    )


def _synthesis_telemetry(
    *,
    model_used: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    latency_ms: int,
    cost_usd: float,
    repair_attempted: bool,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "model_used": _safe_diagnostic_value(model_used) or SYNTH_MODEL,
        "input_tokens": max(0, int(input_tokens)),
        "output_tokens": max(0, int(output_tokens)),
        "total_tokens": max(0, int(total_tokens)),
        "latency_ms": max(0, int(latency_ms)),
        "cost_usd": max(0.0, float(cost_usd)),
        "repair_attempted": bool(repair_attempted),
        "attempts": [dict(attempt) for attempt in attempts],
    }


def _log_openai_response_metadata(
    query_id: str,
    stage: str,
    metadata: dict[str, Any],
) -> None:
    log.info(
        "synthesis_response_metadata query_id=%s stage=%s request_id=%s "
        "finish_reason=%s model=%s input_tokens=%d output_tokens=%d "
        "total_tokens=%d",
        _safe_diagnostic_value(query_id) or "unknown",
        stage,
        metadata.get("request_id") or "unavailable",
        metadata.get("finish_reason") or "unavailable",
        metadata.get("model") or "unknown",
        int(metadata.get("input_tokens") or 0),
        int(metadata.get("output_tokens") or 0),
        int(metadata.get("total_tokens") or 0),
    )


def _log_failed_attempt_totals(
    query_id: str,
    telemetry: dict[str, Any],
) -> None:
    log.warning(
        "synthesis_failed_attempt_totals query_id=%s model=%s "
        "input_tokens=%d output_tokens=%d total_tokens=%d cost_usd=%.8f "
        "failed_synthesis_total_ms=%d repair_attempted=%s",
        _safe_diagnostic_value(query_id) or "unknown",
        telemetry.get("model_used") or "unknown",
        int(telemetry.get("input_tokens") or 0),
        int(telemetry.get("output_tokens") or 0),
        int(telemetry.get("total_tokens") or 0),
        float(telemetry.get("cost_usd") or 0.0),
        int(telemetry.get("latency_ms") or 0),
        bool(telemetry.get("repair_attempted")),
    )


def _trace_validation_error(
    stage: str,
    error: Exception,
    *,
    query_id: str = "unknown",
    model: str = "unknown",
) -> None:
    if not _trace_enabled():
        return
    validation_errors = []
    error_count = 0
    if isinstance(error, ValidationError):
        summary = _validation_error_summary(error)
        validation_errors = summary["errors"]
        error_count = summary["error_count"]
    _trace_event(
        stage,
        {
            "parse_status": "failed",
            "error_type": type(error).__name__,
            "query_id": _safe_diagnostic_value(query_id) or "unknown",
            "model": _safe_diagnostic_value(model) or "unknown",
            "error_count": error_count,
            "validation_errors": validation_errors,
        },
    )


def _trace_result(
    conclusion: TrustedConclusionV2,
    analysis: Optional[ClaimAnalysisV3],
    claim_analysis_status: str,
    answers: list[dict[str, Any]],
) -> None:
    if not _trace_enabled():
        return
    payload = conclusion.model_dump()
    _trace_event(
        "parsed_result",
        {
            "parse_status": "success",
            "schema_version": conclusion.schema_version,
            "result_keys": sorted(str(key) for key in payload),
            "key_findings_count": _safe_list_count(
                payload.get("key_findings")
            ),
            "source_summary_count": _safe_list_count(
                payload.get("source_summary")
            ),
            "provider_assessment_count": _safe_list_count(
                payload.get("provider_assessment")
            ),
            "claim_matrix_count": _safe_list_count(
                payload.get("claim_matrix")
            ),
            "claim_agreements_count": _safe_list_count(
                payload.get("claim_agreements")
            ),
            "claim_disagreements_count": _safe_list_count(
                payload.get("claim_disagreements")
            ),
            "exclusive_contributions_count": _safe_list_count(
                payload.get("exclusive_contributions")
            ),
            "decisive_factors_count": _safe_list_count(
                payload.get("decisive_factors")
            ),
            "claim_count": len(analysis.claims) if analysis else 0,
            "claim_analysis_status": claim_analysis_status,
            "normalized_providers": sorted(
                {
                    str(answer.get("provider_key") or "").strip().lower()
                    for answer in answers
                    if answer.get("provider_key")
                }
            ),
        },
    )


def _trace_event(stage: str, fields: dict[str, Any]) -> None:
    log.info(
        "Structured conclusion trace: %s",
        json.dumps(
            {"stage": stage, **fields},
            ensure_ascii=True,
            sort_keys=True,
        ),
    )


def _safe_list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _normalized_provider_names(payload: dict[str, Any]) -> list[str]:
    names: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str):
            normalized = _PROVIDER_ALIASES.get(value.strip().casefold())
            if normalized:
                names.add(normalized)

    conclusion = payload.get("trusted_conclusion")
    if isinstance(conclusion, dict):
        for agreement in conclusion.get("agreements") or []:
            for provider in agreement.get("supporting_models") or []:
                add(provider)
        for disagreement in conclusion.get("disagreements") or []:
            for position in disagreement.get("positions") or []:
                add(position.get("model"))
        for evidence in conclusion.get("strongest_evidence") or []:
            for provider in evidence.get("supporting_models") or []:
                add(provider)
        for claim in conclusion.get("unsupported_claims") or []:
            for provider in claim.get("originating_models") or []:
                add(provider)

    analysis = payload.get("claim_analysis")
    if isinstance(analysis, dict):
        for claim in analysis.get("claims") or []:
            for field in (
                "originating_models",
                "supporting_models",
                "disputing_models",
            ):
                for provider in claim.get(field) or []:
                    add(provider)
            for excerpt in (
                list(claim.get("support") or [])
                + list(claim.get("dispute") or [])
            ):
                add(excerpt.get("provider"))
    return sorted(names)


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
