export function humanizeEnumValue(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return text
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
export function translateEnum(t, prefix, value) {
  const raw = String(value ?? "").trim();
  if (!raw) return t("results.enums.notAvailable");

  const normalized = raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const key = `${prefix}.${normalized}`;
  const translated = t(key);

  if (translated !== key) return translated;
  return t("results.enums.unknown", { value: humanizeEnumValue(raw) });
}

export function localizeProviderError(t, lang, error, providerStatus) {
  const raw = String(error ?? "").trim();
  if (lang !== "it") {
    return raw || t("results.errors.noProviderResponse");
  }

  const status = String(providerStatus ?? "").toUpperCase();
  const normalized = raw.toLowerCase();

  if (status === "TIMEOUT" || /timed?\s*out|timeout|readtimeout/.test(normalized)) {
    return t("results.errors.providerTimeout");
  }
  if (status === "DISABLED" || /disabled by|provider disabled/.test(normalized)) {
    return t("results.errors.providerDisabled");
  }
  if (/api key.*not configured|api[_\s-]?key.*missing|missing.*api[_\s-]?key/.test(normalized)) {
    return t("results.errors.apiKeyMissing");
  }
  if (/authentication|auth failed|unauthori[sz]ed|\b401\b|\b403\b/.test(normalized)) {
    return t("results.errors.authenticationFailed");
  }
  if (/rate limit|quota|\b429\b/.test(normalized)) {
    return t("results.errors.quotaExceeded");
  }
  if (/network|connection|connecterror|ssl|tls|dns|failed to fetch/.test(normalized)) {
    return t("results.errors.networkError");
  }
  if (/unknown execution status/.test(normalized)) {
    return t("results.errors.unknownExecutionStatus");
  }
  if (/mock content.*blocked|simulated content.*blocked/.test(normalized)) {
    return t("results.errors.mockBlocked");
  }
  if (/query not found|comparison request.*not.*available/.test(normalized)) {
    return t("results.errors.queryNotFound");
  }
  return t("results.errors.providerFailureDetail");
}
