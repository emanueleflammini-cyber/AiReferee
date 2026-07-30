import { safeHttpUrl } from "./claimTraceability";

const ARRAY_FIELDS = [
  "agreements",
  "disagreements",
  "strongest_evidence",
  "remaining_uncertainties",
  "unsupported_claims",
  "what_could_change_the_verdict",
];

export function normalizeStructuredConclusion(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  if (!["2.0", "2.1"].includes(value.schema_version)) return null;
  const finalAnswer = cleanText(value.final_answer || value.final_verdict);
  if (!finalAnswer) return null;
  if (!value.confidence || typeof value.confidence !== "object") return null;

  const normalized = {
    ...value,
    final_answer: finalAnswer,
    final_verdict: cleanText(value.final_verdict) || finalAnswer,
    confidence_reason: cleanText(value.confidence_reason)
      || cleanText(value.confidence.reason),
    referee_reasoning: cleanText(value.referee_reasoning),
    confidence: {
      ...value.confidence,
      level: normalizeLevel(value.confidence.level),
      reason: typeof value.confidence.reason === "string"
        ? value.confidence.reason.trim()
        : "",
      factors: {
        model_agreement: normalizeLevel(value.confidence.factors?.model_agreement),
        evidence_quality: normalizeLevel(value.confidence.factors?.evidence_quality),
        uncertainty: normalizeLevel(value.confidence.factors?.uncertainty),
      },
    },
    key_findings: normalizeKeyFindings(value.key_findings),
    uncertainties: normalizeUncertainties(
      value.uncertainties,
      value.remaining_uncertainties
    ),
    strongest_shared_evidence: normalizeEvidence(
      value.strongest_shared_evidence
    ),
    what_could_change: uniqueStrings(
      Array.isArray(value.what_could_change)
        ? value.what_could_change
        : value.what_could_change_the_verdict
    ),
    provider_assessment: normalizeProviderAssessments(
      value.provider_assessment
    ),
    source_summary: normalizeSourceSummary(value.source_summary),
  };

  ARRAY_FIELDS.forEach((field) => {
    normalized[field] = Array.isArray(value[field]) ? value[field] : [];
  });
  return normalized;
}

export function conclusionEvidenceViewModel({ structured, claims = [] }) {
  const conclusion = normalizeStructuredConclusion(structured);
  if (!conclusion) {
    return {
      conclusion: null,
      keyFindings: [],
      sharedFacts: [],
      agreements: [],
      disagreements: [],
      strongestEvidence: [],
      coveredClaimIds: [],
    };
  }

  const normalizedClaims = (Array.isArray(claims) ? claims : [])
    .map(normalizeTraceableClaim)
    .filter(Boolean);
  const claimById = new Map(normalizedClaims.map((claim) => [claim.id, claim]));
  const sourceById = new Map(
    conclusion.source_summary.map((source) => [source.id, source])
  );
  const resolveClaims = (ids) => uniqueStrings(ids)
    .map((id) => claimById.get(id))
    .filter(Boolean);
  const keyFindings = conclusion.key_findings.map((finding) => ({
    ...finding,
    sources: finding.sourceReferences
      .map((id) => sourceById.get(id))
      .filter(Boolean),
  }));

  const sharedFacts = keyFindings.length
    ? []
    : normalizedClaims.filter((claim) => (
      claim.claimType === "fact"
      && claim.assessmentStatus === "supported"
      && claim.supportingModels.length >= 2
    ));
  const covered = new Set(sharedFacts.map((claim) => claim.id));
  const shownText = new Set(sharedFacts.map((claim) => comparableText(claim.text)));

  const agreements = conclusion.agreements
    .map((agreement) => ({
      ...agreement,
      linkedClaims: resolveClaims(agreement.supporting_claim_ids),
    }))
    .filter((agreement) => {
      const key = comparableText(agreement.claim);
      const repeatsSharedFacts = (
        agreement.linkedClaims.length > 0
        && agreement.linkedClaims.every((claim) => covered.has(claim.id))
      );
      if (repeatsSharedFacts || (key && shownText.has(key))) return false;
      if (key) shownText.add(key);
      agreement.linkedClaims.forEach((claim) => covered.add(claim.id));
      return true;
    });

  const disagreements = conclusion.disagreements
    .map((disagreement) => {
      const linkedClaims = resolveClaims(disagreement.disputing_claim_ids);
      const positions = (Array.isArray(disagreement.positions)
        ? disagreement.positions
        : []
      ).map((position) => ({
        ...position,
        linkedClaims: resolveClaims(position.evidence_claim_ids),
      }));
      return { ...disagreement, linkedClaims, positions };
    })
    .filter((disagreement) => {
      const positionModels = uniqueStrings(
        disagreement.positions.map((position) => position.model)
      );
      const positionTexts = new Set(
        disagreement.positions
          .map((position) => comparableText(position.position))
          .filter(Boolean)
      );
      const isRealDisagreement = positionModels.length >= 2 && positionTexts.size >= 2;
      if (!isRealDisagreement) return false;
      disagreement.linkedClaims.forEach((claim) => covered.add(claim.id));
      disagreement.positions.forEach((position) => {
        position.linkedClaims.forEach((claim) => covered.add(claim.id));
      });
      return true;
    });

  const explicitStrongestShared = Boolean(conclusion.strongest_shared_evidence);
  const strongestEvidenceInput = explicitStrongestShared
    ? [conclusion.strongest_shared_evidence]
    : conclusion.strongest_evidence;
  const strongestEvidence = strongestEvidenceInput
    .map((evidence) => ({
      ...evidence,
      linkedClaims: resolveClaims(evidence.evidence_claim_ids),
    }))
    .filter((evidence) => {
      if (explicitStrongestShared) return true;
      const key = comparableText(evidence.claim);
      const ids = evidence.linkedClaims.map((claim) => claim.id);
      const repeatsKnownClaim = ids.length > 0 && ids.every((id) => covered.has(id));
      if (repeatsKnownClaim || (key && shownText.has(key))) return false;
      if (key) shownText.add(key);
      ids.forEach((id) => covered.add(id));
      return true;
    });

  conclusion.unsupported_claims.forEach((item) => {
    uniqueStrings(item.unsupported_claim_ids).forEach((id) => covered.add(id));
  });
  keyFindings.forEach((finding) => covered.add(finding.id));

  return {
    conclusion,
    keyFindings,
    sharedFacts,
    agreements,
    disagreements,
    strongestEvidence,
    coveredClaimIds: [...covered],
  };
}

export function coveredClaimIdsForConclusion(structured, claims = []) {
  return conclusionEvidenceViewModel({ structured, claims }).coveredClaimIds;
}

export function conclusionViewModel({
  structured,
  legacyText = "",
  synthesisStatus = "",
  synthesisError = "",
}) {
  const normalized = normalizeStructuredConclusion(structured);
  if (normalized) {
    return {
      kind: "structured",
      conclusion: normalized,
      error: "",
    };
  }
  if (String(legacyText || "").trim()) {
    return {
      kind: "legacy",
      conclusion: null,
      legacyText: String(legacyText).trim(),
      error: "",
    };
  }
  return {
    kind: "failed",
    conclusion: null,
    legacyText: "",
    error: synthesisError || (
      synthesisStatus === "FAILED"
        ? "Trusted Conclusion synthesis failed."
        : "Trusted Conclusion is not available."
    ),
  };
}

export function populatedStructuredSections(conclusion) {
  const normalized = normalizeStructuredConclusion(conclusion);
  if (!normalized) return [];
  return ARRAY_FIELDS.filter((field) => normalized[field].length > 0);
}

function normalizeLevel(value) {
  const level = String(value || "").toLowerCase();
  return ["high", "medium", "low"].includes(level) ? level : "low";
}

function normalizeTraceableClaim(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const id = cleanText(value.id);
  const text = cleanText(value.text);
  if (!id || !text) return null;
  return {
    id,
    text,
    claimType: cleanText(value.claim_type),
    assessmentStatus: cleanText(value.assessment?.status).toLowerCase(),
    assessmentReason: cleanText(value.assessment?.reason),
    originatingModels: uniqueStrings(value.originating_models),
    supportingModels: uniqueStrings(value.supporting_models),
    disputingModels: uniqueStrings(value.disputing_models),
    support: normalizeExcerpts(value.support),
    dispute: normalizeExcerpts(value.dispute),
  };
}

function normalizeKeyFindings(values) {
  const statuses = new Set([
    "verified",
    "probable",
    "disputed",
    "uncertain",
    "unsupported",
  ]);
  const strengths = new Set(["strong", "moderate", "weak"]);
  return (Array.isArray(values) ? values : [])
    .map((item) => {
      const id = cleanText(item?.id);
      const claim = cleanText(item?.claim);
      const status = cleanText(item?.status).toLowerCase();
      const evidenceStrength = cleanText(item?.evidence_strength).toLowerCase();
      if (!id || !claim || !statuses.has(status)) return null;
      return {
        id,
        claim,
        status,
        explanation: cleanText(item?.explanation),
        supportingProviders: uniqueStrings(item?.supporting_providers),
        dissentingProviders: uniqueStrings(item?.dissenting_providers),
        evidenceStrength: strengths.has(evidenceStrength)
          ? evidenceStrength
          : "weak",
        sourceReferences: uniqueStrings(item?.source_references),
        relevantExcerpts: (Array.isArray(item?.relevant_excerpts)
          ? item.relevant_excerpts
          : []
        )
          .map((excerpt) => ({
            provider: cleanText(excerpt?.provider),
            excerpt: cleanText(excerpt?.text),
            stance: excerpt?.stance === "dissent" ? "dispute" : "support",
            responseId: cleanText(excerpt?.provider_response_id),
          }))
          .filter((excerpt) => excerpt.provider && excerpt.excerpt),
      };
    })
    .filter(Boolean);
}

function normalizeUncertainties(primary, fallback) {
  const values = Array.isArray(primary)
    ? primary
    : (Array.isArray(fallback) ? fallback : []);
  return values
    .map((item) => ({
      id: cleanText(item?.id),
      description: cleanText(item?.description),
      impact: normalizeLevel(item?.impact),
    }))
    .filter((item) => item.id && item.description);
}

function normalizeEvidence(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const id = cleanText(value.id);
  const claim = cleanText(value.claim);
  if (!id || !claim) return null;
  return {
    ...value,
    id,
    claim,
    description: cleanText(value.description),
    supporting_models: uniqueStrings(value.supporting_models),
    source_status: cleanText(value.source_status),
    evidence_claim_ids: uniqueStrings(value.evidence_claim_ids),
  };
}

function normalizeProviderAssessments(values) {
  return (Array.isArray(values) ? values : [])
    .map((item) => ({
      provider: cleanText(item?.provider),
      usefulContributions: uniqueStrings(item?.useful_contributions),
      weaknesses: uniqueStrings(item?.weaknesses),
      perceivedAccuracy: cleanText(item?.perceived_accuracy) || "not_assessed",
      coherence: cleanText(item?.coherence) || "not_assessed",
      usableCitationIds: uniqueStrings(item?.usable_citation_ids),
    }))
    .filter((item) => item.provider);
}

function normalizeSourceSummary(values) {
  const statuses = new Set([
    "provided_by_model",
    "shared_by_multiple_models",
    "unverified",
    "malformed",
  ]);
  return (Array.isArray(values) ? values : [])
    .map((item) => {
      const id = cleanText(item?.id);
      const status = cleanText(item?.verification_status).toLowerCase();
      if (!id || !statuses.has(status)) return null;
      const rawUrl = cleanText(item?.url);
      return {
        id,
        title: cleanText(item?.title),
        rawUrl,
        clickableUrl: status === "malformed" ? null : safeHttpUrl(rawUrl),
        publisher: cleanText(item?.publisher),
        domain: cleanText(item?.domain),
        citedBy: uniqueStrings(item?.cited_by),
        supportsClaimIds: uniqueStrings(item?.supports_claim_ids),
        verificationStatus: status,
      };
    })
    .filter(Boolean);
}

function normalizeExcerpts(values) {
  return (Array.isArray(values) ? values : [])
    .map((item) => ({
      provider: cleanText(item?.provider),
      excerpt: cleanText(item?.response_excerpt),
    }))
    .filter((item) => item.provider && item.excerpt);
}

function uniqueStrings(values) {
  return [...new Set(
    (Array.isArray(values) ? values : [])
      .map(cleanText)
      .filter(Boolean)
  )];
}

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function comparableText(value) {
  return cleanText(value)
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}
