"""Claim and citation traceability contracts for AI Referee Phase 3.

This module has no provider SDK or database dependency. Citation extraction is
deterministic and preserves provider provenance. Claim validation verifies that
every excerpt is present in the corresponding provider response.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any, Iterable, Literal, Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProviderKey = Literal["openai", "gemini", "mistral"]
ClaimType = Literal[
    "fact",
    "interpretation",
    "recommendation",
    "prediction",
    "uncertainty",
]
ClaimStatus = Literal["supported", "disputed", "weak", "unsupported"]
SourceType = Literal[
    "provider_metadata",
    "provider_inline_url",
    "provider_markdown_link",
    "provider_named_source_without_url",
]
VerificationStatus = Literal[
    "unverified",
    "invalid_url",
    "missing_url",
    "verified",
]
ExtractionMethod = Literal[
    "provider_metadata",
    "markdown_link",
    "plain_text_url",
    "explicit_source_label",
]
ExecutionMode = Literal["LIVE", "DEMO"]

_MARKDOWN_LINK_RE = re.compile(
    r"\[(?P<title>[^\]\r\n]{1,300})\]\(\s*(?P<url>[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)
_PLAIN_HTTP_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>{}\[\]\"']+")
_EXPLICIT_SOURCE_RE = re.compile(
    r"(?im)^\s*(?:sources?|fonti?|fuentes?|quellen?)\s*:\s*(?P<title>[^\r\n]{2,300})\s*$"
)
_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}'\""


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class CitationProvenance(StrictModel):
    provider: ProviderKey
    extraction_method: ExtractionMethod


class CitationRecord(StrictModel):
    id: str = Field(pattern=r"^citation_[a-f0-9]{12}$")
    provider: ProviderKey
    declared_by_models: list[ProviderKey] = Field(min_length=1)
    title: Optional[str] = Field(default=None, max_length=300)
    url: Optional[str] = Field(default=None, max_length=2048)
    domain: Optional[str] = Field(default=None, max_length=253)
    source_type: SourceType
    verification_status: VerificationStatus
    associated_claim_ids: list[str] = Field(default_factory=list)
    extraction_method: ExtractionMethod
    provenance: list[CitationProvenance] = Field(min_length=1)
    verification_evidence: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_url_state(self) -> "CitationRecord":
        normalized, domain = normalize_safe_url(self.url)
        if normalized:
            if self.verification_status in ("invalid_url", "missing_url"):
                raise ValueError("safe URL cannot be invalid_url or missing_url")
            if self.url != normalized or self.domain != domain:
                raise ValueError("citation URL/domain are not normalized")
        elif self.url:
            if self.verification_status != "invalid_url":
                raise ValueError("unsafe URL must be marked invalid_url")
            if self.domain is not None:
                raise ValueError("unsafe URL must not expose a domain")
        else:
            if self.verification_status != "missing_url":
                raise ValueError("citation without URL must be marked missing_url")
            if self.domain is not None:
                raise ValueError("citation without URL must not expose a domain")
        if self.verification_status == "verified" and not self.verification_evidence:
            raise ValueError("verified citation requires genuine verification evidence")
        return self


class ProviderResponseReference(StrictModel):
    provider_response_id: str = Field(min_length=1, max_length=100)
    start_hint: Optional[str] = Field(default=None, max_length=160)
    end_hint: Optional[str] = Field(default=None, max_length=160)


class ClaimSupport(StrictModel):
    provider: ProviderKey
    response_excerpt: str = Field(min_length=1, max_length=500)
    response_reference: ProviderResponseReference


class ClaimAssessment(StrictModel):
    status: ClaimStatus
    reason: str = Field(min_length=1, max_length=1000)


class TraceableClaim(StrictModel):
    id: str = Field(pattern=r"^claim_[A-Za-z0-9_-]{1,80}$")
    text: str = Field(min_length=1, max_length=1200)
    claim_type: ClaimType
    originating_models: list[ProviderKey] = Field(min_length=1)
    supporting_models: list[ProviderKey] = Field(default_factory=list)
    disputing_models: list[ProviderKey] = Field(default_factory=list)
    support: list[ClaimSupport] = Field(default_factory=list)
    dispute: list[ClaimSupport] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    assessment: ClaimAssessment

    @model_validator(mode="after")
    def validate_relationships(self) -> "TraceableClaim":
        supporters = set(self.supporting_models)
        disputers = set(self.disputing_models)
        if supporters & disputers:
            raise ValueError("a provider cannot both support and dispute one claim")
        support_providers = {item.provider for item in self.support}
        if not support_providers.issubset(supporters):
            raise ValueError("support excerpts require a supporting provider")
        dispute_providers = {item.provider for item in self.dispute}
        if not dispute_providers.issubset(disputers):
            raise ValueError("dispute excerpts require a disputing provider")
        if self.assessment.status == "supported" and not self.support:
            raise ValueError("supported claim requires at least one real excerpt")
        if self.assessment.status == "disputed" and not disputers:
            raise ValueError("disputed claim requires at least one disputing provider")
        return self


class ClaimAnalysisV3(StrictModel):
    schema_version: Literal["3.0"] = "3.0"
    execution_mode: ExecutionMode
    claims: list[TraceableClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_claim_ids(self) -> "ClaimAnalysisV3":
        ids = [claim.id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim IDs must be unique within the result")
        return self


def normalize_safe_url(raw_url: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return a normalized safe HTTP(S) URL and domain, or ``(None, None)``.

    URLs with credentials, local/private hosts, control characters or unsafe
    schemes are rejected. No request is made.
    """
    if not raw_url or not isinstance(raw_url, str):
        return None, None
    raw = raw_url.strip().strip("<>")
    if not raw or len(raw) > 2048 or any(ord(char) < 32 for char in raw):
        return None, None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None, None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None, None
    if parsed.username or parsed.password:
        return None, None
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return None, None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        return None, None
    try:
        port = parsed.port
    except ValueError:
        return None, None
    netloc = f"[{hostname}]" if address and address.version == 6 else hostname
    if port and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = parsed.path or "/"
    normalized = urlunsplit(
        (parsed.scheme.lower(), netloc, path, parsed.query, "")
    )
    return normalized, hostname


def extract_citations(
    text: str,
    provider: str,
    metadata: Optional[Iterable[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Extract only citations explicitly present in provider output/metadata."""
    provider_key = _provider_key(provider)
    candidates: list[dict[str, Any]] = []

    for item in metadata or []:
        if not isinstance(item, dict):
            continue
        raw_url = _string_or_none(item.get("url") or item.get("uri"))
        title = _string_or_none(item.get("title") or item.get("name"))
        if not raw_url and not title:
            continue
        candidates.append(
            _citation_candidate(
                provider_key,
                title,
                raw_url,
                "provider_metadata",
                "provider_metadata",
            )
        )

    markdown_spans: list[tuple[int, int]] = []
    for match in _MARKDOWN_LINK_RE.finditer(text or ""):
        markdown_spans.append(match.span())
        candidates.append(
            _citation_candidate(
                provider_key,
                match.group("title"),
                match.group("url"),
                "provider_markdown_link",
                "markdown_link",
            )
        )

    for match in _PLAIN_HTTP_URL_RE.finditer(text or ""):
        if any(start <= match.start() < end for start, end in markdown_spans):
            continue
        raw_url = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        candidates.append(
            _citation_candidate(
                provider_key,
                None,
                raw_url,
                "provider_inline_url",
                "plain_text_url",
            )
        )

    for match in _EXPLICIT_SOURCE_RE.finditer(text or ""):
        title = match.group("title").strip()
        if _PLAIN_HTTP_URL_RE.search(title) or _MARKDOWN_LINK_RE.search(title):
            continue
        candidates.append(
            _citation_candidate(
                provider_key,
                title,
                None,
                "provider_named_source_without_url",
                "explicit_source_label",
            )
        )

    return deduplicate_citations(candidates)


def deduplicate_citations(
    citations: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate normalized URLs while retaining all provider provenance."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in citations:
        citation = CitationRecord.model_validate(raw).model_dump()
        key = (
            f"url:{citation['url']}"
            if citation.get("url") and citation["verification_status"] != "invalid_url"
            else (
                f"invalid:{citation['provider']}:{citation.get('url') or ''}"
                if citation.get("url")
                else f"named:{citation['provider']}:{(citation.get('title') or '').lower()}"
            )
        )
        if key not in merged:
            merged[key] = citation
            order.append(key)
            continue
        current = merged[key]
        current["declared_by_models"] = _ordered_unique(
            current["declared_by_models"] + citation["declared_by_models"]
        )
        provenance = current["provenance"] + citation["provenance"]
        current["provenance"] = [
            item
            for index, item in enumerate(provenance)
            if item not in provenance[:index]
        ]
        if not current.get("title") and citation.get("title"):
            current["title"] = citation["title"]
    return [merged[key] for key in order]


def merge_provider_citations(
    groups: Iterable[Iterable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return deduplicate_citations(
        citation
        for group in groups
        for citation in group
    )


def validate_claim_analysis(
    raw: dict[str, Any],
    allowed_answers: Iterable[dict[str, Any]],
    citations: Iterable[dict[str, Any]],
    execution_mode: str,
) -> ClaimAnalysisV3:
    """Validate provider references, citation IDs and real response excerpts."""
    analysis = ClaimAnalysisV3.model_validate(raw)
    expected_mode = "DEMO" if execution_mode == "DEMO" else "LIVE"
    if analysis.execution_mode != expected_mode:
        raise ValueError("claim analysis execution mode does not match comparison")

    answers = list(allowed_answers)
    expected_status = "MOCK" if expected_mode == "DEMO" else "LIVE"
    if any(
        str(answer.get("provider_status") or "").upper() != expected_status
        for answer in answers
    ):
        raise ValueError("claim evidence crosses LIVE and DEMO execution modes")
    response_by_provider = {
        str(answer.get("provider_key")): str(answer.get("text") or "")
        for answer in answers
    }
    response_id_by_provider = {
        str(answer.get("provider_key")): str(
            answer.get("provider_response_id")
            or answer.get("provider_key")
        )
        for answer in answers
    }
    allowed = set(response_by_provider)
    citation_by_id = {
        citation["id"]: citation
        for citation in citations
        if isinstance(citation, dict) and citation.get("id")
    }

    for claim in analysis.claims:
        referenced = (
            set(claim.originating_models)
            | set(claim.supporting_models)
            | set(claim.disputing_models)
            | {support.provider for support in claim.support}
            | {dispute.provider for dispute in claim.dispute}
        )
        if not referenced.issubset(allowed):
            raise ValueError("claim references a FAILED or absent provider")
        for support in claim.support:
            response = response_by_provider[support.provider]
            if not _excerpt_in_response(support.response_excerpt, response):
                raise ValueError("claim excerpt is not present in provider response")
            expected_id = response_id_by_provider[support.provider]
            if support.response_reference.provider_response_id != expected_id:
                raise ValueError("claim response reference does not match provider")
            for hint in (
                support.response_reference.start_hint,
                support.response_reference.end_hint,
            ):
                if hint and not _excerpt_in_response(hint, response):
                    raise ValueError("claim response hint is not present in response")
        for dispute in claim.dispute:
            response = response_by_provider[dispute.provider]
            if not _excerpt_in_response(dispute.response_excerpt, response):
                raise ValueError(
                    "claim dispute excerpt is not present in provider response"
                )
            expected_id = response_id_by_provider[dispute.provider]
            if dispute.response_reference.provider_response_id != expected_id:
                raise ValueError(
                    "claim dispute response reference does not match provider"
                )
            for hint in (
                dispute.response_reference.start_hint,
                dispute.response_reference.end_hint,
            ):
                if hint and not _excerpt_in_response(hint, response):
                    raise ValueError(
                        "claim dispute response hint is not present in response"
                    )
        for citation_id in claim.citation_ids:
            citation = citation_by_id.get(citation_id)
            if not citation:
                raise ValueError("claim references an unknown citation")
            provenance = set(citation.get("declared_by_models") or [])
            if not provenance.intersection(
                set(claim.originating_models) | set(claim.supporting_models)
            ):
                raise ValueError("citation provenance does not match claim providers")
        # Preserve one exact excerpt per provider and semantic excerpt. The
        # synthesizer can occasionally repeat the same quotation with different
        # whitespace; exposing duplicates adds no provenance and clutters the UI.
        claim.support = _deduplicate_claim_excerpts(claim.support)
        claim.dispute = _deduplicate_claim_excerpts(claim.dispute)
    return analysis


def associate_citations_with_claims(
    citations: Iterable[dict[str, Any]],
    analysis: ClaimAnalysisV3,
) -> list[dict[str, Any]]:
    associated: dict[str, list[str]] = {}
    for claim in analysis.claims:
        for citation_id in claim.citation_ids:
            associated.setdefault(citation_id, []).append(claim.id)
    output = []
    for raw in citations:
        item = dict(raw)
        item["associated_claim_ids"] = _ordered_unique(
            associated.get(item["id"], [])
        )
        output.append(CitationRecord.model_validate(item).model_dump())
    return output


def normalize_stored_traceability(
    record: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if record.get("claim_schema_version") != "3.0":
        return [], [], "legacy"
    raw_claims = record.get("claims")
    raw_citations = record.get("citations")
    mode = record.get("execution_mode", "LIVE")
    if not isinstance(raw_claims, list) or not isinstance(raw_citations, list):
        return [], [], "legacy"
    try:
        analysis = ClaimAnalysisV3.model_validate(
            {
                "schema_version": record.get("claim_schema_version"),
                "execution_mode": mode,
                "claims": raw_claims,
            }
        )
        citations = [
            CitationRecord.model_validate(item).model_dump()
            for item in raw_citations
        ]
    except Exception:
        return [], [], "legacy"
    return [claim.model_dump() for claim in analysis.claims], citations, "3.0"


def _citation_candidate(
    provider: ProviderKey,
    title: Optional[str],
    raw_url: Optional[str],
    source_type: SourceType,
    method: ExtractionMethod,
) -> dict[str, Any]:
    cleaned_url = raw_url.strip().strip("<>") if raw_url else None
    normalized_url, domain = normalize_safe_url(cleaned_url)
    if normalized_url:
        stored_url = normalized_url
        verification_status: VerificationStatus = "unverified"
    elif cleaned_url:
        stored_url = cleaned_url[:2048]
        verification_status = "invalid_url"
    else:
        stored_url = None
        verification_status = "missing_url"
    title_value = _string_or_none(title)
    identity = normalized_url or f"{provider}|{stored_url or ''}|{(title_value or '').lower()}"
    citation_id = "citation_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return CitationRecord(
        id=citation_id,
        provider=provider,
        declared_by_models=[provider],
        title=title_value,
        url=stored_url,
        domain=domain,
        source_type=source_type,
        verification_status=verification_status,
        associated_claim_ids=[],
        extraction_method=method,
        provenance=[
            CitationProvenance(
                provider=provider,
                extraction_method=method,
            )
        ],
    ).model_dump()


def _provider_key(value: str) -> ProviderKey:
    normalized = str(value or "").strip().lower()
    if normalized in ("model-a", "openai", "chatgpt"):
        return "openai"
    if normalized in ("model-c", "gemini", "google", "google deepmind"):
        return "gemini"
    if normalized in ("model-e", "mistral", "mistral ai"):
        return "mistral"
    raise ValueError("unsupported provider for traceability")


def _string_or_none(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:300] if text else None


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _deduplicate_claim_excerpts(
    excerpts: Iterable[ClaimSupport],
) -> list[ClaimSupport]:
    unique: list[ClaimSupport] = []
    seen: set[tuple[str, str]] = set()
    for excerpt in excerpts:
        normalized = _WHITESPACE_RE.sub(
            " ",
            excerpt.response_excerpt,
        ).strip().casefold()
        key = (excerpt.provider, normalized)
        if key in seen:
            continue
        seen.add(key)
        unique.append(excerpt)
    return unique


def _excerpt_in_response(excerpt: str, response: str) -> bool:
    if excerpt in response:
        return True
    normalized_excerpt = _WHITESPACE_RE.sub(" ", excerpt).strip()
    normalized_response = _WHITESPACE_RE.sub(" ", response).strip()
    return bool(normalized_excerpt and normalized_excerpt in normalized_response)
