import { renderToStaticMarkup } from "react-dom/server";
import { ClaimTraceability } from "./ClaimTraceability";
import { safeHttpUrl, traceabilityViewModel } from "../lib/claimTraceability";

const t = (key) => key;
const liveStatuses = { openai: "LIVE", gemini: "LIVE" };

const support = (provider, excerpt = "The exact supporting sentence.") => ({
  provider,
  response_excerpt: excerpt,
  response_reference: { provider_response_id: provider },
});

const claim = (overrides = {}) => ({
  id: "claim_1",
  text: "A supported material claim.",
  claim_type: "fact",
  originating_models: ["openai", "gemini"],
  supporting_models: ["openai", "gemini"],
  disputing_models: [],
  support: [support("openai"), support("gemini")],
  citation_ids: [],
  assessment: { status: "supported", reason: "Both live providers support it." },
  ...overrides,
});

const props = (overrides = {}) => ({
  claims: [claim()],
  citations: [],
  claimAnalysisStatus: "SUCCESS",
  providerStatuses: liveStatuses,
  executionMode: "LIVE",
  t,
  ...overrides,
});

const structuredFinding = (overrides = {}) => ({
  id: "claim_structured",
  claim: "A traceable 2.1 claim.",
  status: "probable",
  explanation: "The live provider responses support this conclusion.",
  supporting_providers: ["openai", "gemini"],
  dissenting_providers: [],
  evidence_strength: "strong",
  source_references: [],
  relevant_excerpts: [
    {
      provider: "openai",
      text: "The exact OpenAI excerpt.",
      stance: "support",
      provider_response_id: "openai",
    },
    {
      provider: "gemini",
      text: "The exact Gemini excerpt.",
      stance: "support",
      provider_response_id: "gemini",
    },
  ],
  ...overrides,
});

const structured21 = (overrides = {}) => ({
  schema_version: "2.1",
  key_findings: [structuredFinding()],
  source_summary: [],
  provider_assessment: [],
  ...overrides,
});

describe("claim traceability", () => {
  test("renders a supported claim and its real excerpts", () => {
    const html = renderToStaticMarkup(<ClaimTraceability {...props()} />);
    expect(html).toContain("data-testid=\"trace-supported\"");
    expect(html).toContain("A supported material claim.");
    expect(html).toContain("The exact supporting sentence.");
    expect(html).toContain("ChatGPT");
    expect(html).toContain("Gemini");
  });

  test("renders disputed claims separately", () => {
    const disputed = claim({
      id: "claim_2",
      text: "The models disagree.",
      supporting_models: ["openai"],
      disputing_models: ["gemini"],
      support: [support("openai")],
      dispute: [support("gemini", "The exact contrary sentence.")],
      assessment: { status: "disputed", reason: "Gemini gives a competing position." },
    });
    const html = renderToStaticMarkup(
      <ClaimTraceability {...props({ claims: [disputed] })} />
    );
    expect(html).toContain("data-testid=\"trace-disputed\"");
    expect(html).toContain("The models disagree.");
    expect(html).toContain("The exact contrary sentence.");
    expect(html).toContain("results.traceability.contraryExcerpt");
  });

  test("labels provider citations as unverified and opens safe links safely", () => {
    const citation = {
      id: "citation_123456789abc",
      provider: "openai",
      declared_by_models: ["openai"],
      title: "Provider source",
      url: "https://example.com/report",
      domain: "example.com",
      source_type: "provider_markdown_link",
      verification_status: "unverified",
      associated_claim_ids: ["claim_1"],
      extraction_method: "markdown_link",
    };
    const html = renderToStaticMarkup(
      <ClaimTraceability {...props({ citations: [citation] })} />
    );
    expect(html).toContain("data-testid=\"citation-status-unverified\"");
    expect(html).toContain("href=\"https://example.com/report\"");
    expect(html).toContain("rel=\"noopener noreferrer nofollow\"");
  });

  test("hides the legacy source list when the 2.1 conclusion renders it", () => {
    const citation = {
      id: "citation_123456789abc",
      provider: "openai",
      declared_by_models: ["openai"],
      title: "Provider source",
      url: "https://example.com/source",
      domain: "example.com",
      source_type: "provider_inline_url",
      verification_status: "unverified",
      associated_claim_ids: [],
      extraction_method: "plain_text_url",
    };
    const html = renderToStaticMarkup(
      <ClaimTraceability
        {...props({ claims: [], citations: [citation] })}
        hideSources
      />
    );
    expect(html).not.toContain("data-testid=\"trace-sources\"");
    expect(html).not.toContain("data-testid=\"claim-traceability\"");
  });

  test("does not make unsafe URLs clickable", () => {
    const citation = {
      id: "citation_abcdef123456",
      provider: "openai",
      declared_by_models: ["openai"],
      title: "Unsafe source",
      url: "javascript:alert(1)",
      verification_status: "invalid_url",
      extraction_method: "markdown_link",
    };
    const html = renderToStaticMarkup(
      <ClaimTraceability {...props({ citations: [citation] })} />
    );
    expect(html).toContain("Unsafe source");
    expect(html).not.toContain("href=");
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
  });

  test("hides empty and unavailable sections for Phase 2 and legacy records", () => {
    const empty = renderToStaticMarkup(
      <ClaimTraceability
        {...props({ claims: [], citations: [], claimAnalysisStatus: "SUCCESS" })}
      />
    );
    const phase2 = renderToStaticMarkup(
      <ClaimTraceability {...props({ claims: undefined, claimAnalysisStatus: "NOT_AVAILABLE" })} />
    );
    const legacy = renderToStaticMarkup(
      <ClaimTraceability {...props({ claims: undefined, claimAnalysisStatus: "" })} />
    );
    expect(empty).toBe("");
    expect(phase2).toBe("");
    expect(legacy).toBe("");
  });

  test("removes FAILED providers from support and hides invalid supported claims", () => {
    const view = traceabilityViewModel({
      claims: [claim({ supporting_models: ["gemini"], support: [support("gemini")] })],
      citations: [],
      claimAnalysisStatus: "SUCCESS",
      providerStatuses: { openai: "LIVE", gemini: "FAILED" },
      executionMode: "LIVE",
    });
    expect(view.supported).toEqual([]);
  });

  test("keeps LIVE claim sections independent from mockData values", () => {
    const html = renderToStaticMarkup(<ClaimTraceability {...props()} />);
    expect(html).not.toContain("92%");
    expect(html).not.toContain("Consensus strengthened");
    expect(html).not.toContain("MOCK");
  });

  test("keeps DEMO claims separate from LIVE claims", () => {
    const view = traceabilityViewModel({
      claims: [claim()],
      citations: [],
      claimAnalysisStatus: "SUCCESS",
      providerStatuses: { openai: "MOCK", gemini: "MOCK" },
      executionMode: "LIVE",
    });
    expect(view.supported).toEqual([]);
  });

  test("excludes claims already explained by the structured conclusion", () => {
    const html = renderToStaticMarkup(
      <ClaimTraceability {...props({ excludeClaimIds: ["claim_1"] })} />
    );
    expect(html).toBe("");
    const view = traceabilityViewModel({
      claims: [claim()],
      citations: [],
      claimAnalysisStatus: "SUCCESS",
      providerStatuses: liveStatuses,
      executionMode: "LIVE",
      excludeClaimIds: ["claim_1"],
    });
    expect(view.supported).toEqual([]);
  });

  test("uses real 2.1 findings when the parallel claim payload is unavailable", () => {
    const html = renderToStaticMarkup(
      <ClaimTraceability
        {...props({
          claims: [],
          structuredConclusion: structured21(),
          claimAnalysisStatus: "FAILED",
          claimAnalysisError: "Legacy status does not match the 2.1 payload.",
          providerStatuses: [
            { provider_name: "OpenAI", provider_status: "LIVE" },
            { provider_name: "Google DeepMind", provider_status: "LIVE" },
          ],
        })}
      />
    );
    expect(html).toContain("data-testid=\"claim-traceability\"");
    expect(html).toContain("data-testid=\"trace-supported\"");
    expect(html).toContain("A traceable 2.1 claim.");
    expect(html).toContain("The exact OpenAI excerpt.");
    expect(html).toContain("The exact Gemini excerpt.");
    expect(html).not.toContain("data-testid=\"claim-traceability-failed\"");
  });

  test("keeps a real 2.1 claim visible when it has no excerpts or sources", () => {
    const html = renderToStaticMarkup(
      <ClaimTraceability
        {...props({
          claims: [],
          structuredConclusion: structured21({
            key_findings: [structuredFinding({
              relevant_excerpts: [],
              source_references: [],
            })],
          }),
          claimAnalysisStatus: "NOT_AVAILABLE",
        })}
      />
    );
    expect(html).toContain("A traceable 2.1 claim.");
    expect(html).not.toContain("results.traceability.showExcerpts");
    expect(html).not.toContain("data-testid=\"trace-sources\"");
  });

  test("renders only genuine 2.1 sources linked to known findings", () => {
    const source = {
      id: "citation_123456789abc",
      title: "Provider-declared source",
      url: "https://example.com/report",
      publisher: "Example",
      domain: "example.com",
      cited_by: ["openai"],
      supports_claim_ids: ["claim_structured"],
      verification_status: "provided_by_model",
    };
    const html = renderToStaticMarkup(
      <ClaimTraceability
        {...props({
          claims: [],
          structuredConclusion: structured21({ source_summary: [source] }),
          claimAnalysisStatus: "SUCCESS",
        })}
      />
    );
    expect(html).toContain("data-testid=\"trace-sources\"");
    expect(html).toContain("Provider-declared source");
    expect(html).toContain("href=\"https://example.com/report\"");
  });

  test("keeps supporting and dissenting providers distinct for 2.1 claims", () => {
    const finding = structuredFinding({
      status: "disputed",
      supporting_providers: ["openai"],
      dissenting_providers: ["gemini"],
      relevant_excerpts: [
        {
          provider: "openai",
          text: "The supporting position.",
          stance: "support",
          provider_response_id: "openai",
        },
        {
          provider: "gemini",
          text: "The contrary position.",
          stance: "dissent",
          provider_response_id: "gemini",
        },
      ],
    });
    const html = renderToStaticMarkup(
      <ClaimTraceability
        {...props({
          claims: [],
          structuredConclusion: structured21({ key_findings: [finding] }),
          claimAnalysisStatus: "SUCCESS",
        })}
      />
    );
    expect(html).toContain("data-testid=\"trace-disputed\"");
    expect(html).toContain("The supporting position.");
    expect(html).toContain("The contrary position.");
    expect(html).toContain("results.traceability.contraryExcerpt");
  });

  test("does not turn legacy or empty data into traceability", () => {
    const failed = renderToStaticMarkup(
      <ClaimTraceability
        {...props({
          claims: [],
          structuredConclusion: { schema_version: "2.0", key_findings: [] },
          claimAnalysisStatus: "FAILED",
        })}
      />
    );
    const unavailable = renderToStaticMarkup(
      <ClaimTraceability
        {...props({
          claims: [],
          structuredConclusion: null,
          claimAnalysisStatus: "NOT_AVAILABLE",
        })}
      />
    );
    expect(failed).toContain("data-testid=\"claim-traceability-failed\"");
    expect(unavailable).toBe("");
  });

  test("filters FAILED and cross-mode MOCK providers from 2.1 evidence", () => {
    const structuredConclusion = structured21({
      key_findings: [
        structuredFinding({
          supporting_providers: ["gemini"],
          relevant_excerpts: [{
            provider: "gemini",
            text: "Gemini-only evidence.",
            stance: "support",
            provider_response_id: "gemini",
          }],
        }),
      ],
    });
    const failedView = traceabilityViewModel({
      claims: [],
      citations: [],
      structuredConclusion,
      claimAnalysisStatus: "SUCCESS",
      providerStatuses: { gemini: "FAILED" },
      executionMode: "LIVE",
    });
    const mockInLiveView = traceabilityViewModel({
      claims: [],
      citations: [],
      structuredConclusion,
      claimAnalysisStatus: "SUCCESS",
      providerStatuses: { gemini: "MOCK" },
      executionMode: "LIVE",
    });
    const demoView = traceabilityViewModel({
      claims: [],
      citations: [],
      structuredConclusion,
      claimAnalysisStatus: "SUCCESS",
      providerStatuses: { gemini: "MOCK" },
      executionMode: "DEMO",
    });
    expect(failedView.supported).toEqual([]);
    expect(mockInLiveView.supported).toEqual([]);
    expect(demoView.supported).toHaveLength(1);
  });
});
