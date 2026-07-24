import {
  PROVIDER_STATUS,
  normalizeProviderResponses,
} from "../lib/executionMode";

describe("provider execution safety", () => {
  test("keeps a real provider response LIVE", () => {
    const [result] = normalizeProviderResponses([
      { id: "model-a", text: "real", provider_status: "LIVE" },
    ], "LIVE");

    expect(result.provider_status).toBe(PROVIDER_STATUS.LIVE);
    expect(result.text).toBe("real");
    expect(result.is_mock).toBe(false);
  });

  test("blocks mock content in LIVE mode", () => {
    const [result] = normalizeProviderResponses([
      { id: "model-a", text: "demo", provider_status: "MOCK", is_mock: true },
    ], "LIVE");

    expect(result.provider_status).toBe(PROVIDER_STATUS.FAILED);
    expect(result.text).toBe("");
    expect(result.provider_error).toMatch(/blocked/i);
  });

  test("allows mock content only in DEMO mode", () => {
    const [result] = normalizeProviderResponses([
      { id: "model-c", text: "demo", provider_status: "MOCK", is_mock: true },
    ], "DEMO");

    expect(result.provider_status).toBe(PROVIDER_STATUS.MOCK);
    expect(result.text).toBe("demo");
    expect(result.is_mock).toBe(true);
  });

  test("never displays text from a failed provider", () => {
    const [result] = normalizeProviderResponses([
      {
        id: "model-c",
        text: "must disappear",
        provider_status: "FAILED",
        provider_error: "quota exceeded",
      },
    ], "LIVE");

    expect(result.provider_status).toBe(PROVIDER_STATUS.FAILED);
    expect(result.text).toBe("");
    expect(result.provider_error).toBe("quota exceeded");
  });
});
