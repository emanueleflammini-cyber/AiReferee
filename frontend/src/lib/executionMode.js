export const PROVIDER_STATUS = {
  LIVE: "LIVE",
  FAILED: "FAILED",
  MOCK: "MOCK",
};

export function failedProviderResponses(models, reason) {
  return models.map((model) => ({
    id: model.id,
    label: model.label,
    codename: model.codename,
    provider: model.provider,
    provider_name: model.provider,
    text: "",
    provider_status: PROVIDER_STATUS.FAILED,
    execution_mode: "LIVE",
    provider_error: reason,
    error: reason,
    provider_latency: 0,
    latency_ms: 0,
    is_mock: false,
  }));
}

export function normalizeProviderResponses(responses, executionMode) {
  return (responses || []).map((response) => {
    let status = String(
      response.provider_status
      || (response.is_mock ? PROVIDER_STATUS.MOCK : response.error ? PROVIDER_STATUS.FAILED : PROVIDER_STATUS.LIVE),
    ).toUpperCase();
    let error = response.provider_error || response.error || null;
    let text = response.text || "";

    if (!Object.values(PROVIDER_STATUS).includes(status)) {
      status = PROVIDER_STATUS.FAILED;
      error = error || "Provider returned an unknown execution status.";
      text = "";
    }
    if (executionMode === "LIVE" && status === PROVIDER_STATUS.MOCK) {
      status = PROVIDER_STATUS.FAILED;
      error = "Mock content was blocked in LIVE execution mode.";
      text = "";
    }
    if (status === PROVIDER_STATUS.FAILED) {
      text = "";
    }

    return {
      ...response,
      text,
      provider_status: status,
      execution_mode: executionMode,
      provider_error: error,
      error,
      is_mock: status === PROVIDER_STATUS.MOCK,
    };
  });
}
