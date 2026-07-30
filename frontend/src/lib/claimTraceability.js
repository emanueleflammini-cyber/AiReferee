const CLAIM_STATUSES = new Set(["supported", "disputed", "weak", "unsupported"]);
const PROVIDER_STATUSES = new Set(["LIVE", "FAILED", "TIMEOUT", "DISABLED", "MOCK"]);

export function safeHttpUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = new URL(value);
    if (!["http:", "https:"].includes(parsed.protocol)) return null;
    if (parsed.username || parsed.password) return null;
    const hostname = parsed.hostname.toLowerCase();
    if (
      !hostname
      || hostname === "localhost"
      || hostname.endsWith(".localhost")
      || isPrivateAddress(hostname)
    ) {
      return null;
    }
    return parsed.href;
  } catch {
    return null;
  }
}

export function traceabilityViewModel({
  claims,
  citations,
  structuredConclusion,
  claimAnalysisStatus,
  claimAnalysisError,
  providerStatuses,
  executionMode = "LIVE",
  excludeClaimIds = [],
}) {
  const status = String(claimAnalysisStatus || "").toUpperCase();
  const statusMap = normalizeProviderStatuses(providerStatuses);
  const expectedStatus = executionMode === "DEMO" ? "MOCK" : "LIVE";
  const providerIsEligible = (provider) => {
    if (!Object.keys(statusMap).length) return true;
    return statusMap[providerKey(provider)] === expectedStatus;
  };
  const excluded = new Set(
    (Array.isArray(excludeClaimIds) ? excludeClaimIds : [])
      .map(cleanText)
      .filter(Boolean)
  );
  const structured = normalizeStructuredTraceability(
    structuredConclusion,
    providerIsEligible,
    excluded
  );

  // Version 2.1 is enriched only after the backend has validated the underlying
  // claim analysis, so its embedded provenance is authoritative when present.
  if (structured.hasData) {
    return {
      kind: "available",
      error: "",
      ...structured.view,
    };
  }

  if (status === "FAILED") {
    return {
      kind: "failed",
      error: claimAnalysisError || "Claim traceability is unavailable.",
      supported: [],
      disputed: [],
      weak: [],
      citations: [],
    };
  }

  if (status !== "SUCCESS" || !Array.isArray(claims)) {
    return {
      kind: "not_available",
      error: "",
      supported: [],
      disputed: [],
      weak: [],
      citations: [],
    };
  }

  const normalizedClaims = claims
    .map((claim) => normalizeClaim(claim, providerIsEligible))
    .filter((claim) => claim && !excluded.has(claim.id));
  const knownClaimIds = new Set(normalizedClaims.map((claim) => claim.id));
  const normalizedCitations = (Array.isArray(citations) ? citations : [])
    .map((citation) => normalizeCitation(citation, providerIsEligible, knownClaimIds))
    .filter(Boolean);

  return {
    kind: "available",
    error: "",
    supported: normalizedClaims.filter((claim) => claim.assessment.status === "supported"),
    disputed: normalizedClaims.filter((claim) => claim.assessment.status === "disputed"),
    weak: normalizedClaims.filter((claim) => ["weak", "unsupported"].includes(claim.assessment.status)),
    citations: normalizedCitations,
  };
}

function normalizeStructuredTraceability(value, providerIsEligible, excluded) {
  if (
    !value
    || typeof value !== "object"
    || Array.isArray(value)
    || value.schema_version !== "2.1"
  ) {
    return emptyStructuredTraceability();
  }

  const findings = (Array.isArray(value.key_findings) ? value.key_findings : [])
    .map((finding) => normalizeStructuredFinding(finding, providerIsEligible))
    .filter((finding) => finding && !excluded.has(finding.id));
  const knownClaimIds = new Set(findings.map((finding) => finding.id));
  const sources = (Array.isArray(value.source_summary) ? value.source_summary : [])
    .map((source) => normalizeStructuredSource(
      source,
      providerIsEligible,
      knownClaimIds
    ))
    .filter(Boolean);

  return {
    hasData: findings.length > 0 || sources.length > 0,
    view: {
      supported: findings.filter(
        (finding) => finding.assessment.status === "supported"
      ),
      disputed: findings.filter(
        (finding) => finding.assessment.status === "disputed"
      ),
      weak: findings.filter(
        (finding) => ["weak", "unsupported"].includes(
          finding.assessment.status
        )
      ),
      citations: sources,
    },
  };
}

function normalizeStructuredFinding(value, providerIsEligible) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const id = cleanText(value.id);
  const text = cleanText(value.claim);
  const reason = cleanText(value.explanation);
  if (!id || !text || !reason) return null;

  const supportingModels = uniqueProviders(
    value.supporting_providers,
    providerIsEligible
  );
  const disputingModels = uniqueProviders(
    value.dissenting_providers,
    providerIsEligible
  );
  const excerpts = (Array.isArray(value.relevant_excerpts)
    ? value.relevant_excerpts
    : []
  )
    .map((excerpt) => normalizeStructuredExcerpt(
      excerpt,
      providerIsEligible
    ))
    .filter(Boolean);
  const support = excerpts.filter((excerpt) => excerpt.stance === "support");
  const dispute = excerpts.filter((excerpt) => excerpt.stance === "dispute");
  const rawStatus = cleanText(value.status).toLowerCase();
  const assessmentStatus = disputingModels.length > 0 || rawStatus === "disputed"
    ? "disputed"
    : ["verified", "probable"].includes(rawStatus) && supportingModels.length > 0
      ? "supported"
      : rawStatus === "unsupported"
        ? "unsupported"
        : "weak";
  const originatingModels = [...new Set([
    ...supportingModels,
    ...disputingModels,
  ])];
  if (!originatingModels.length) return null;

  return {
    id,
    text,
    claimType: "",
    originatingModels,
    supportingModels,
    disputingModels,
    support,
    dispute,
    citationIds: Array.isArray(value.source_references)
      ? value.source_references.map(cleanText).filter(Boolean)
      : [],
    assessment: {
      status: assessmentStatus,
      reason,
    },
  };
}

function normalizeStructuredExcerpt(value, providerIsEligible) {
  const provider = providerKey(cleanText(value?.provider));
  const excerpt = cleanText(value?.text);
  if (!provider || !providerIsEligible(provider) || !excerpt) return null;
  return {
    provider,
    excerpt,
    responseId: cleanText(value?.provider_response_id),
    stance: value?.stance === "dissent" ? "dispute" : "support",
  };
}

function normalizeStructuredSource(value, providerIsEligible, knownClaimIds) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const id = cleanText(value.id);
  const declaredByModels = uniqueProviders(value.cited_by, providerIsEligible);
  if (!id || !declaredByModels.length) return null;
  const rawStatus = cleanText(value.verification_status).toLowerCase();
  const rawUrl = cleanText(value.url);
  const verificationStatus = rawStatus === "malformed"
    ? "invalid_url"
    : "unverified";
  return {
    id,
    provider: declaredByModels[0],
    declaredByModels,
    title: cleanText(value.title),
    rawUrl,
    clickableUrl: verificationStatus === "invalid_url"
      ? null
      : safeHttpUrl(rawUrl),
    domain: cleanText(value.domain),
    sourceType: "",
    verificationStatus,
    extractionMethod: "",
    associatedClaimIds: Array.isArray(value.supports_claim_ids)
      ? value.supports_claim_ids
        .map(cleanText)
        .filter((claimId) => claimId && knownClaimIds.has(claimId))
      : [],
  };
}

function emptyStructuredTraceability() {
  return {
    hasData: false,
    view: {
      supported: [],
      disputed: [],
      weak: [],
      citations: [],
    },
  };
}

function normalizeClaim(value, providerIsEligible) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const id = cleanText(value.id);
  const text = cleanText(value.text);
  const assessmentStatus = String(value.assessment?.status || "").toLowerCase();
  const assessmentReason = cleanText(value.assessment?.reason);
  if (!id || !text || !CLAIM_STATUSES.has(assessmentStatus) || !assessmentReason) return null;

  const originatingModels = uniqueProviders(value.originating_models, providerIsEligible);
  const supportingModels = uniqueProviders(value.supporting_models, providerIsEligible);
  const disputingModels = uniqueProviders(value.disputing_models, providerIsEligible);
  const support = (Array.isArray(value.support) ? value.support : [])
    .map((item) => normalizeSupport(item, providerIsEligible))
    .filter(Boolean);
  const dispute = (Array.isArray(value.dispute) ? value.dispute : [])
    .map((item) => normalizeSupport(item, providerIsEligible))
    .filter(Boolean);

  if (
    assessmentStatus === "supported"
    && (!supportingModels.length || !support.length)
  ) {
    return null;
  }
  if (assessmentStatus === "disputed" && !disputingModels.length) return null;
  if (!originatingModels.length && !supportingModels.length && !disputingModels.length) return null;

  return {
    id,
    text,
    claimType: cleanText(value.claim_type),
    originatingModels,
    supportingModels,
    disputingModels,
    support,
    dispute,
    citationIds: Array.isArray(value.citation_ids)
      ? value.citation_ids.map(cleanText).filter(Boolean)
      : [],
    assessment: {
      status: assessmentStatus,
      reason: assessmentReason,
    },
  };
}

function normalizeSupport(value, providerIsEligible) {
  const provider = cleanText(value?.provider);
  const excerpt = cleanText(value?.response_excerpt);
  if (!provider || !providerIsEligible(provider) || !excerpt) return null;
  return {
    provider,
    excerpt,
    responseId: cleanText(value?.response_reference?.provider_response_id),
  };
}

function normalizeCitation(value, providerIsEligible, knownClaimIds) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const provider = cleanText(value.provider);
  const declaredByModels = uniqueProviders(value.declared_by_models, providerIsEligible);
  if (!provider || !providerIsEligible(provider) || !declaredByModels.length) return null;
  const verificationStatus = cleanText(value.verification_status) || "unverified";
  const rawUrl = cleanText(value.url);
  const clickableUrl = verificationStatus === "invalid_url" ? null : safeHttpUrl(rawUrl);
  return {
    id: cleanText(value.id),
    provider,
    declaredByModels,
    title: cleanText(value.title),
    rawUrl,
    clickableUrl,
    domain: cleanText(value.domain),
    sourceType: cleanText(value.source_type),
    verificationStatus,
    extractionMethod: cleanText(value.extraction_method),
    associatedClaimIds: Array.isArray(value.associated_claim_ids)
      ? value.associated_claim_ids.map(cleanText).filter((id) => id && knownClaimIds.has(id))
      : [],
  };
}

function normalizeProviderStatuses(value) {
  if (!value) return {};
  if (!Array.isArray(value) && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .map(([provider, status]) => [providerKey(provider), String(status || "").toUpperCase()])
        .filter(([provider, status]) => provider && PROVIDER_STATUSES.has(status))
    );
  }
  if (!Array.isArray(value)) return {};
  return Object.fromEntries(
    value
      .map((item) => [
        providerKey(item?.provider_key || item?.provider_name || item?.id),
        String(item?.provider_status || "").toUpperCase(),
      ])
      .filter(([provider, status]) => provider && PROVIDER_STATUSES.has(status))
  );
}

function providerKey(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["model-a", "openai", "chatgpt"].includes(normalized)) return "openai";
  if (
    ["model-c", "gemini", "google", "google deepmind"].includes(normalized)
  ) return "gemini";
  if (["model-e", "mistral", "mistral ai"].includes(normalized)) return "mistral";
  return normalized;
}

function uniqueProviders(values, predicate) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.map(providerKey).filter((provider) => provider && predicate(provider)))];
}

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function isPrivateAddress(hostname) {
  const unwrapped = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (
    unwrapped === "::1"
    || unwrapped === "::"
    || unwrapped.startsWith("fc")
    || unwrapped.startsWith("fd")
    || unwrapped.startsWith("fe8")
    || unwrapped.startsWith("fe9")
    || unwrapped.startsWith("fea")
    || unwrapped.startsWith("feb")
  ) {
    return true;
  }
  const ipv4 = hostname.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!ipv4) return false;
  const octets = ipv4.slice(1).map(Number);
  if (octets.some((octet) => octet > 255)) return true;
  return (
    octets[0] === 10
    || octets[0] === 127
    || (octets[0] === 169 && octets[1] === 254)
    || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31)
    || (octets[0] === 192 && octets[1] === 168)
  );
}
