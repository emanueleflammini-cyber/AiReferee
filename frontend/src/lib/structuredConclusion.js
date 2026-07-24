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
  if (value.schema_version !== "2.0") return null;
  if (typeof value.final_answer !== "string" || !value.final_answer.trim()) return null;
  if (!value.confidence || typeof value.confidence !== "object") return null;

  const normalized = {
    ...value,
    final_answer: value.final_answer.trim(),
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
  };

  ARRAY_FIELDS.forEach((field) => {
    normalized[field] = Array.isArray(value[field]) ? value[field] : [];
  });
  return normalized;
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
