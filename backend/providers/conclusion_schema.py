"""Validated Trusted Conclusion 2.0 contract.

This module contains no provider SDK code, so its validation and filtering
helpers can be tested without network credentials.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Literal, Optional, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


Strength = Literal["strong", "moderate", "weak"]
Impact = Literal["high", "medium", "low"]
ConfidenceLevel = Literal["high", "medium", "low"]
AssessmentLevel = Literal["high", "medium", "low", "not_assessed"]
ProviderKey = Literal["openai", "gemini", "mistral"]
FindingStatus = Literal[
    "verified",
    "probable",
    "disputed",
    "uncertain",
    "unsupported",
]
FindingStance = Literal["support", "dissent"]
SourceVerificationStatus = Literal[
    "provided_by_model",
    "shared_by_multiple_models",
    "unverified",
    "malformed",
]
SourceStatus = Literal[
    "model_reasoning",
    "provider_citation_unverified",
    "no_source",
]
ProviderPositionType = Literal[
    "supports",
    "partially_supports",
    "contradicts",
    "uncertain",
    "not_mentioned",
]
AgreementLevel = Literal[
    "unanimous",
    "strong_consensus",
    "partial_consensus",
    "disputed",
    "unresolved",
]
DisagreementType = Literal[
    "factual",
    "interpretation",
    "degree",
    "timeframe",
    "uncertainty",
    "emphasis",
]
VerdictImpact = Literal["high", "medium", "low", "none"]
VerificationStatus = Literal[
    "supported_within_response",
    "unverified",
    "inferential",
    "contradicted",
]

PROVIDER_KEYS_BY_ID = {
    "model-a": "openai",
    "model-c": "gemini",
    "model-e": "mistral",
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
    supporting_claim_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_distinct_supporters(self) -> "Agreement":
        if len(set(self.supporting_models)) < 2:
            raise ValueError("an agreement requires two distinct providers")
        return self


class DisagreementPosition(StrictContractModel):
    """One provider's position within trusted_conclusion.disagreements[].

    Belongs only to Disagreement, never to ClaimDisagreement.
    """

    model: ProviderKey = Field(
        description=(
            "Provider key for this position. Named 'model' because this "
            "belongs to trusted_conclusion.disagreements[]; the equivalent "
            "field in trusted_conclusion.claim_disagreements[] is named "
            "'provider' instead."
        )
    )
    position: str = Field(min_length=1)
    evidence_claim_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Claim IDs from claim_analysis.claims supporting this position. "
            "Valid only inside trusted_conclusion.disagreements[]; "
            "claim_disagreements[].positions[] has no such field."
        ),
    )


class Disagreement(StrictContractModel):
    """A narrative disagreement in trusted_conclusion.disagreements[].

    Distinct from ClaimDisagreement (trusted_conclusion.claim_disagreements[]).
    This structure never carries disagreement_type, impact_on_verdict or
    referee_resolution.
    """

    id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    positions: list[DisagreementPosition] = Field(min_length=2)
    referee_assessment: str = Field(
        min_length=1,
        description=(
            "Required narrative assessment of this disagreement. Only "
            "valid in trusted_conclusion.disagreements[]; "
            "claim_disagreements[] has no referee_assessment field."
        ),
    )
    missing_information: str = Field(
        default="",
        description=(
            "What additional information could resolve this disagreement. "
            "Only valid in trusted_conclusion.disagreements[]."
        ),
    )
    disputing_claim_ids: list[str] = Field(default_factory=list)

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
    evidence_claim_ids: list[str] = Field(default_factory=list)


class RemainingUncertainty(StrictContractModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    impact: Impact


class UnsupportedClaim(StrictContractModel):
    id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    originating_models: list[ProviderKey] = Field(min_length=1)
    reason: str = Field(min_length=1)
    unsupported_claim_ids: list[str] = Field(default_factory=list)


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


class FindingExcerpt(StrictContractModel):
    provider: ProviderKey
    text: str = Field(min_length=1, max_length=500)
    stance: FindingStance
    provider_response_id: str = Field(min_length=1, max_length=100)


class KeyFinding(StrictContractModel):
    id: str = Field(pattern=r"^claim_[A-Za-z0-9_-]{1,80}$")
    claim: str = Field(min_length=1, max_length=1200)
    status: FindingStatus
    explanation: str = Field(min_length=1, max_length=1000)
    supporting_providers: list[ProviderKey] = Field(default_factory=list)
    dissenting_providers: list[ProviderKey] = Field(default_factory=list)
    evidence_strength: Strength
    source_references: list[str] = Field(default_factory=list)
    relevant_excerpts: list[FindingExcerpt] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_provider_stances(self) -> "KeyFinding":
        supporters = set(self.supporting_providers)
        dissenters = set(self.dissenting_providers)
        if supporters & dissenters:
            raise ValueError(
                "a provider cannot both support and dissent from one key finding"
            )
        for excerpt in self.relevant_excerpts:
            expected = supporters if excerpt.stance == "support" else dissenters
            if excerpt.provider not in expected:
                raise ValueError(
                    "key finding excerpt does not match its provider stance"
                )
        return self


class ProviderAssessment(StrictContractModel):
    provider: ProviderKey
    useful_contributions: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    perceived_accuracy: AssessmentLevel = "not_assessed"
    coherence: AssessmentLevel = "not_assessed"
    usable_citation_ids: list[str] = Field(default_factory=list)


class SourceSummaryItem(StrictContractModel):
    id: str = Field(pattern=r"^citation_[a-f0-9]{12}$")
    title: Optional[str] = Field(default=None, max_length=300)
    url: Optional[str] = Field(default=None, max_length=2048)
    publisher: Optional[str] = Field(default=None, max_length=253)
    domain: Optional[str] = Field(default=None, max_length=253)
    cited_by: list[ProviderKey] = Field(min_length=1)
    supports_claim_ids: list[str] = Field(default_factory=list)
    verification_status: SourceVerificationStatus

    @model_validator(mode="after")
    def validate_source_state(self) -> "SourceSummaryItem":
        if self.url:
            try:
                parsed = urlsplit(self.url)
            except ValueError as exc:
                raise ValueError("source summary URL is malformed") from exc
            if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
                raise ValueError("source summary URL must be HTTP(S)")
        if self.verification_status == "malformed" and self.url:
            raise ValueError("malformed source must not expose a clickable URL")
        return self


class ClaimProviderPosition(StrictContractModel):
    provider: ProviderKey
    display_name: str = Field(min_length=1, max_length=100)
    position: ProviderPositionType
    summary: str = Field(default="", max_length=1000)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel

    @model_validator(mode="after")
    def require_position_summary(self) -> "ClaimProviderPosition":
        if self.position != "not_mentioned" and not self.summary:
            raise ValueError(
                "provider position summary is required unless the claim was "
                "not mentioned"
            )
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("provider position evidence refs must be unique")
        return self


class ClaimMatrixItem(StrictContractModel):
    claim_id: str = Field(pattern=r"^claim_[A-Za-z0-9_-]{1,80}$")
    claim: str = Field(min_length=1, max_length=1200)
    importance: Impact
    provider_positions: list[ClaimProviderPosition] = Field(min_length=1)
    agreement_level: AgreementLevel
    referee_assessment: str = Field(min_length=1, max_length=1200)
    evidence_limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_positions_and_agreement(self) -> "ClaimMatrixItem":
        providers = [position.provider for position in self.provider_positions]
        if len(providers) != len(set(providers)):
            raise ValueError(
                "claim matrix contains duplicate provider positions"
            )
        positions = {position.position for position in self.provider_positions}
        if self.agreement_level == "unanimous" and positions != {"supports"}:
            raise ValueError(
                "unanimous requires every participating provider to support "
                "the claim"
            )
        if self.agreement_level == "strong_consensus":
            supporters = sum(
                position.position == "supports"
                for position in self.provider_positions
            )
            if supporters < 2 or "contradicts" in positions:
                raise ValueError(
                    "strong consensus requires two supporters and no "
                    "contradiction"
                )
        if self.agreement_level == "disputed":
            has_support = bool(
                positions & {"supports", "partially_supports"}
            )
            if not has_support or "contradicts" not in positions:
                raise ValueError(
                    "disputed requires supporting and contradicting positions"
                )
        return self


class ClaimAgreement(StrictContractModel):
    topic: str = Field(min_length=1, max_length=500)
    claim_ids: list[str] = Field(min_length=1)
    providers: list[ProviderKey] = Field(min_length=2)
    strength: Impact
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def require_distinct_values(self) -> "ClaimAgreement":
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("agreement claim IDs must be unique")
        if len(set(self.providers)) < 2:
            raise ValueError("claim agreement requires two distinct providers")
        return self


class ClaimDisagreementPosition(StrictContractModel):
    """One provider's position within trusted_conclusion.claim_disagreements[].

    Belongs only to ClaimDisagreement, never to Disagreement.
    """

    provider: ProviderKey = Field(
        description=(
            "Provider key for this position. Named 'provider' because this "
            "belongs to trusted_conclusion.claim_disagreements[]; the "
            "equivalent field in trusted_conclusion.disagreements[] is "
            "named 'model' instead."
        )
    )
    position: str = Field(min_length=1, max_length=1000)


class ClaimDisagreement(StrictContractModel):
    """A structured disagreement in trusted_conclusion.claim_disagreements[],
    linked to claim_matrix claim_ids.

    Distinct from Disagreement (trusted_conclusion.disagreements[]). This
    structure never carries evidence_claim_ids (inside positions) or
    referee_assessment.
    """

    topic: str = Field(min_length=1, max_length=500)
    claim_ids: list[str] = Field(
        min_length=1,
        description="Must reference claim_matrix claim_ids, never evidence_claim_ids.",
    )
    positions: list[ClaimDisagreementPosition] = Field(min_length=2)
    disagreement_type: DisagreementType = Field(
        description=(
            "Only valid in trusted_conclusion.claim_disagreements[]; "
            "trusted_conclusion.disagreements[] has no disagreement_type "
            "field."
        )
    )
    impact_on_verdict: VerdictImpact = Field(
        description=(
            "Only valid in trusted_conclusion.claim_disagreements[]; "
            "trusted_conclusion.disagreements[] has no impact_on_verdict "
            "field."
        )
    )
    referee_resolution: str = Field(
        min_length=1,
        max_length=1200,
        description=(
            "Only valid in trusted_conclusion.claim_disagreements[]; "
            "trusted_conclusion.disagreements[] has no referee_resolution "
            "field."
        ),
    )

    @model_validator(mode="after")
    def require_distinct_values(self) -> "ClaimDisagreement":
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("disagreement claim IDs must be unique")
        providers = [position.provider for position in self.positions]
        if len(providers) != len(set(providers)):
            raise ValueError(
                "claim disagreement requires distinct provider positions"
            )
        return self


class ExclusiveContribution(StrictContractModel):
    provider: ProviderKey
    contribution: str = Field(min_length=1, max_length=1200)
    related_claim_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus
    referee_note: str = Field(min_length=1, max_length=1000)


class DecisiveFactor(StrictContractModel):
    factor: str = Field(min_length=1, max_length=1200)
    supported_by: list[ProviderKey] = Field(default_factory=list)
    opposed_by: list[ProviderKey] = Field(default_factory=list)
    weight: Impact
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def validate_provider_stances(self) -> "DecisiveFactor":
        supporters = set(self.supported_by)
        opponents = set(self.opposed_by)
        if supporters & opponents:
            raise ValueError(
                "a provider cannot both support and oppose a decisive factor"
            )
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
    referee_reasoning: str = ""
    what_could_change_the_verdict: list[str] = Field(default_factory=list)
    claim_matrix: list[ClaimMatrixItem] = Field(default_factory=list)
    claim_agreements: list[ClaimAgreement] = Field(default_factory=list)
    claim_disagreements: list[ClaimDisagreement] = Field(default_factory=list)
    exclusive_contributions: list[ExclusiveContribution] = Field(
        default_factory=list
    )
    decisive_factors: list[DecisiveFactor] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_conclusion_contract(self) -> "TrustedConclusionV2":
        for value in _iter_strings(
            self.model_dump(),
            ignored_keys={"source_summary"},
        ):
            if _URL_RE.search(value):
                raise ValueError(
                    "Trusted Conclusion narrative fields must not contain source "
                    "URLs; sources belong in the deterministic source summary"
                )
        claim_ids = [item.claim_id for item in self.claim_matrix]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim matrix IDs must be unique")
        known_claim_ids = set(claim_ids)
        for section, entries in (
            ("agreement", self.claim_agreements),
            ("disagreement", self.claim_disagreements),
            ("exclusive contribution", self.exclusive_contributions),
        ):
            for entry in entries:
                references = (
                    entry.related_claim_ids
                    if isinstance(entry, ExclusiveContribution)
                    else entry.claim_ids
                )
                unknown = set(references) - known_claim_ids
                if unknown:
                    raise ValueError(
                        f"{section} references unknown claim IDs: "
                        + ", ".join(sorted(unknown))
                    )
        agreement_keys = {
            (
                _comparison_key(item.topic),
                tuple(sorted(item.claim_ids)),
            )
            for item in self.claim_agreements
        }
        if len(agreement_keys) != len(self.claim_agreements):
            raise ValueError("duplicate structured agreements are not allowed")
        disagreement_keys = {
            (
                _comparison_key(item.topic),
                tuple(sorted(item.claim_ids)),
            )
            for item in self.claim_disagreements
        }
        if len(disagreement_keys) != len(self.claim_disagreements):
            raise ValueError(
                "duplicate structured disagreements are not allowed"
            )
        if agreement_keys & disagreement_keys:
            raise ValueError(
                "the same topic and claims cannot be both an agreement and "
                "a disagreement"
            )

        matrix_by_id = {
            item.claim_id: item
            for item in self.claim_matrix
        }
        for agreement in self.claim_agreements:
            eligible = {
                position.provider
                for claim_id in agreement.claim_ids
                for position in matrix_by_id[claim_id].provider_positions
                if position.position in ("supports", "partially_supports")
            }
            if not set(agreement.providers).issubset(eligible):
                raise ValueError(
                    "agreement providers are incompatible with claim matrix "
                    "positions"
                )
        for disagreement in self.claim_disagreements:
            matrix_positions = {
                position.provider: position.position
                for claim_id in disagreement.claim_ids
                for position in matrix_by_id[claim_id].provider_positions
            }
            if not {
                position.provider for position in disagreement.positions
            }.issubset(matrix_positions):
                raise ValueError(
                    "disagreement provider is absent from the claim matrix"
                )
            position_values = set(matrix_positions.values())
            incompatible = (
                "contradicts" in position_values
                and bool(
                    position_values
                    & {"supports", "partially_supports"}
                )
            )
            if not incompatible:
                raise ValueError(
                    "disagreement is incompatible with provider positions"
                )
        return self


class TrustedConclusionV21(TrustedConclusionV2):
    """Backward-compatible 2.1 result enriched from validated claim evidence."""

    schema_version: Literal["2.1"] = "2.1"
    final_verdict: str = Field(min_length=1)
    confidence_reason: str = Field(min_length=1)
    key_findings: list[KeyFinding] = Field(default_factory=list)
    uncertainties: list[RemainingUncertainty] = Field(default_factory=list)
    strongest_shared_evidence: Optional[EvidenceItem] = None
    what_could_change: list[str] = Field(default_factory=list)
    provider_assessment: list[ProviderAssessment] = Field(default_factory=list)
    source_summary: list[SourceSummaryItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_compatibility_aliases(self) -> "TrustedConclusionV21":
        if self.final_verdict != self.final_answer:
            raise ValueError("final_verdict must match the legacy final_answer")
        if self.confidence_reason != self.confidence.reason:
            raise ValueError(
                "confidence_reason must match the structured confidence reason"
            )
        citation_ids = {source.id for source in self.source_summary}
        finding_ids = {finding.id for finding in self.key_findings}
        for finding in self.key_findings:
            if not set(finding.source_references).issubset(citation_ids):
                raise ValueError("key finding references an unknown source")
        for source in self.source_summary:
            if not set(source.supports_claim_ids).issubset(finding_ids):
                raise ValueError("source summary references an unknown finding")
        for assessment in self.provider_assessment:
            if not set(assessment.usable_citation_ids).issubset(citation_ids):
                raise ValueError(
                    "provider assessment references an unknown source"
                )
        return self


TrustedConclusion = Union[TrustedConclusionV2, TrustedConclusionV21]


def _iter_strings(
    value: Any,
    ignored_keys: Optional[set[str]] = None,
) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if ignored_keys and key in ignored_keys:
                continue
            yield from _iter_strings(item, ignored_keys)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item, ignored_keys)


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
    if "mistral" in haystack:
        return "mistral"
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
                "provider_response_id": str(
                    _value(response, "provider_response_id") or provider_key
                ),
                "provider_key": provider_key,
                "label": str(_value(response, "label") or provider_key),
                "provider": str(
                    _value(response, "provider_name")
                    or _value(response, "provider")
                    or provider_key
                ),
                "provider_status": status,
                "text": text,
                "citations": list(_value(response, "citations") or []),
            }
        )
    return answers


def parse_structured_conclusion(
    raw: str | dict[str, Any],
    allowed_providers: Iterable[str],
) -> TrustedConclusion:
    """Parse strict JSON and reject references to providers outside the panel."""
    payload: Any
    if isinstance(raw, dict):
        payload = raw
    else:
        payload = json.loads(_extract_json_object(raw))

    model = (
        TrustedConclusionV21
        if payload.get("schema_version") == "2.1"
        else TrustedConclusionV2
    )
    conclusion = model.model_validate(payload)
    allowed = {str(provider).strip().lower() for provider in allowed_providers}
    referenced = set(_provider_references(conclusion))
    unknown = sorted(reference for reference in referenced if reference not in allowed)
    if unknown:
        raise ValueError(
            "Conclusion references providers outside the current execution: "
            + ", ".join(unknown)
        )
    for item in conclusion.claim_matrix:
        positioned = {
            position.provider.lower()
            for position in item.provider_positions
        }
        if positioned != allowed:
            missing = sorted(allowed - positioned)
            extra = sorted(positioned - allowed)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("unexpected " + ", ".join(extra))
            raise ValueError(
                "claim matrix must contain one position for every "
                "participating provider"
                + (": " + "; ".join(details) if details else "")
            )
    if (
        len(allowed) == 1
        and conclusion.confidence.factors.model_agreement != "low"
    ):
        raise ValueError(
            "a single-provider conclusion must report low model agreement"
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
        matrix_providers = {
            str(position.get("provider") or "").strip().lower()
            for item in raw.get("claim_matrix") or []
            if isinstance(item, dict)
            for position in item.get("provider_positions") or []
            if isinstance(position, dict)
            and position.get("provider")
        }
        conclusion = parse_structured_conclusion(
            raw,
            allowed_providers=(
                matrix_providers or set(ProviderKey.__args__)
            ),
        )
    except Exception:  # Corrupt/partial stored data must not crash old results.
        return None, "legacy"
    return conclusion.model_dump(), conclusion.schema_version


def _provider_references(conclusion: TrustedConclusion) -> Iterable[str]:
    for agreement in conclusion.agreements:
        yield from (model.lower() for model in agreement.supporting_models)
    for disagreement in conclusion.disagreements:
        yield from (position.model.lower() for position in disagreement.positions)
    for evidence in conclusion.strongest_evidence:
        yield from (model.lower() for model in evidence.supporting_models)
    for claim in conclusion.unsupported_claims:
        yield from (model.lower() for model in claim.originating_models)
    for matrix_item in conclusion.claim_matrix:
        for position in matrix_item.provider_positions:
            yield position.provider.lower()
    for agreement in conclusion.claim_agreements:
        yield from (provider.lower() for provider in agreement.providers)
    for disagreement in conclusion.claim_disagreements:
        for position in disagreement.positions:
            yield position.provider.lower()
    for contribution in conclusion.exclusive_contributions:
        yield contribution.provider.lower()
    for factor in conclusion.decisive_factors:
        yield from (
            provider.lower()
            for provider in factor.supported_by + factor.opposed_by
        )
    if isinstance(conclusion, TrustedConclusionV21):
        for finding in conclusion.key_findings:
            yield from (
                model.lower()
                for model in (
                    finding.supporting_providers
                    + finding.dissenting_providers
                )
            )
        for assessment in conclusion.provider_assessment:
            yield assessment.provider.lower()
        for source in conclusion.source_summary:
            yield from (model.lower() for model in source.cited_by)


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


def _comparison_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
