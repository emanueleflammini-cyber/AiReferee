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
});
