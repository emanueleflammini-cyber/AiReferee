"""Validated Trusted Conclusion 2.0 contract.

This module contains no provider SDK code, so its validation and filtering
helpers can be tested without network credentials.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


Strength = Literal["strong", "moderate", "weak"]
Impact = Literal["high", "medium", "low"]
ConfidenceLevel = Literal["high", "medium", "low"]
ProviderKey = Literal["openai", "gemini"]
SourceStatus = Literal[
    "model_reasoning",
    "provider_citation_unverified",
    "no_source",
]

PROVIDER_KEYS_BY_ID = {
    "model-a": "openai",
    "model-c": "gemini",
}

_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)")
_NUMERIC_CONFIDENCE_RE = re.compile(r"(?i)\b\d{1,3}\s*(?:%|percent\b)")


class StrictContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class Agreement(StrictContractModel):
    id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    supporting_models: list[ProviderKey] = Field(min_length=2)
    strength: Strength
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_distinct_supporters(self) -> "Agreement":
        if len(set(self.supporting_models)) < 2:
            raise ValueError("an agreement requires two distinct providers")
        return self


class DisagreementPosition(StrictContractModel):
    model: ProviderKey
    position: str = Field(min_length=1)


class Disagreement(StrictContractModel):
    id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    positions: list[DisagreementPosition] = Field(min_length=2)
    referee_assessment: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_distinct_positions(self) -> "Disagreement":
        if len({position.model for position in self.positions}) < 2:
            raise ValueError("a disagreement requires two distinct providers")
        return self


class EvidenceItem(StrictContractModel):
    id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    description: str = Field(min_length=1)
    supporting_models: list[ProviderKey] = Field(min_length=1)
    source_status: SourceStatus


class RemainingUncertainty(StrictContractModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    impact: Impact


class UnsupportedClaim(StrictContractModel):
    id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    originating_models: list[ProviderKey] = Field(min_length=1)
    reason: str = Field(min_length=1)


class ConfidenceFactors(StrictContractModel):
    model_agreement: ConfidenceLevel
    evidence_quality: ConfidenceLevel
    uncertainty: ConfidenceLevel


class ConclusionConfidence(StrictContractModel):
    level: ConfidenceLevel
    reason: str = Field(min_length=1)
    factors: ConfidenceFactors

    @model_validator(mode="after")
    def reject_numeric_confidence(self) -> "ConclusionConfidence":
        if _NUMERIC_CONFIDENCE_RE.search(self.reason):
            raise ValueError("confidence.reason must be qualitative, not numeric")
        return self


class TrustedConclusionV2(StrictContractModel):
    schema_version: Literal["2.0"] = "2.0"
    final_answer: str = Field(min_length=1)
    agreements: list[Agreement] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    strongest_evidence: list[EvidenceItem] = Field(default_factory=list)
    remaining_uncertainties: list[RemainingUncertainty] = Field(default_factory=list)
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    confidence: ConclusionConfidence
    what_could_change_the_verdict: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_urls(self) -> "TrustedConclusionV2":
        for value in _iter_strings(self.model_dump()):
            if _URL_RE.search(value):
                raise ValueError(
                    "Trusted Conclusion 2.0 must not contain source URLs; "
                    "independent citation verification is not enabled"
                )
        return self


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def provider_key_for_response(response: Any) -> str:
    """Return the stable public provider key used by the conclusion schema."""
    response_id = _value(response, "id")
    if response_id in PROVIDER_KEYS_BY_ID:
        return PROVIDER_KEYS_BY_ID[response_id]

    haystack = " ".join(
        str(_value(response, name) or "")
        for name in ("provider_name", "provider", "label")
    ).lower()
    if "gemini" in haystack or "google" in haystack:
        return "gemini"
    if "openai" in haystack or "chatgpt" in haystack:
        return "openai"
    return str(response_id or "unknown").strip().lower()


def eligible_synthesis_answers(
    responses: Iterable[Any],
    execution_mode: str,
) -> list[dict[str, str]]:
    """Select evidence from this execution only.

    LIVE conclusions accept only LIVE responses. DEMO conclusions accept only
    MOCK responses. FAILED, empty and cross-mode responses are always ignored.
    """
    normalized_mode = "DEMO" if execution_mode == "DEMO" else "LIVE"
    required_status = "MOCK" if normalized_mode == "DEMO" else "LIVE"
    answers: list[dict[str, str]] = []
    for response in responses:
        status = str(_value(response, "provider_status") or "").upper()
        text = str(_value(response, "text") or "").strip()
        if status != required_status or not text:
            continue
        provider_key = provider_key_for_response(response)
        answers.append(
            {
                "id": str(_value(response, "id") or provider_key),
                "provider_key": provider_key,
                "label": str(_value(response, "label") or provider_key),
                "provider": str(
                    _value(response, "provider_name")
                    or _value(response, "provider")
                    or provider_key
                ),
                "provider_status": status,
                "text": text,
            }
        )
    return answers


def parse_structured_conclusion(
    raw: str | dict[str, Any],
    allowed_providers: Iterable[str],
) -> TrustedConclusionV2:
    """Parse strict JSON and reject references to providers outside the panel."""
    payload: Any
    if isinstance(raw, dict):
        payload = raw
    else:
        payload = json.loads(_extract_json_object(raw))

    conclusion = TrustedConclusionV2.model_validate(payload)
    allowed = {str(provider).strip().lower() for provider in allowed_providers}
    referenced = set(_provider_references(conclusion))
    unknown = sorted(reference for reference in referenced if reference not in allowed)
    if unknown:
        raise ValueError(
            "Conclusion references providers outside the current execution: "
            + ", ".join(unknown)
        )
    return conclusion


def normalize_stored_conclusion(
    record: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], str]:
    """Return validated structured data or a non-fabricated legacy marker."""
    raw = record.get("trusted_conclusion_structured")
    if not isinstance(raw, dict):
        return None, "legacy"
    try:
        conclusion = TrustedConclusionV2.model_validate(raw)
    except Exception:  # Corrupt/partial stored data must not crash old results.
        return None, "legacy"
    return conclusion.model_dump(), "2.0"


def _provider_references(conclusion: TrustedConclusionV2) -> Iterable[str]:
    for agreement in conclusion.agreements:
        yield from (model.lower() for model in agreement.supporting_models)
    for disagreement in conclusion.disagreements:
        yield from (position.model.lower() for position in disagreement.positions)
    for evidence in conclusion.strongest_evidence:
        yield from (model.lower() for model in evidence.supporting_models)
    for claim in conclusion.unsupported_claims:
        yield from (model.lower() for model in claim.originating_models)


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


def _value(response: Any, name: str) -> Any:
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name, None)
