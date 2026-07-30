import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { StructuredConclusion } from "./StructuredConclusion";
import en from "../locales/en.json";

const get = (bundle, path) => (
  path.split(".").reduce((value, key) => value?.[key], bundle)
);
const t = (key) => get(en, key) ?? key;

const structured = {
  schema_version: "2.0",
  final_answer: "The evidence supports a measured conclusion.",
  agreements: [],
  disagreements: [],
  strongest_evidence: [],
  remaining_uncertainties: [],
  unsupported_claims: [],
  confidence: {
    level: "high",
    reason: "Two independent providers support the central claim.",
    factors: {
      model_agreement: "high",
      evidence_quality: "medium",
      uncertainty: "low",
    },
  },
  referee_reasoning: "The shared direction outweighs the limited disagreement.",
  what_could_change_the_verdict: ["A stronger independent source."],
  claim_matrix: [
    {
      claim_id: "claim-one",
      claim: "Automation affects repetitive work first.",
      importance: "high",
      provider_positions: [
        {
          provider: "openai",
          display_name: "ChatGPT",
          position: "supports",
          summary: "ChatGPT supports the claim and explains that repetitive tasks are easier to automate.",
          evidence_refs: ["openai-response"],
          confidence: "high",
        },
        {
          provider: "gemini",
          display_name: "Gemini",
          position: "partially_supports",
          summary: "Gemini agrees with the direction but qualifies the expected scale.",
          evidence_refs: ["gemini-response"],
          confidence: "medium",
        },
      ],
      agreement_level: "strong_consensus",
      referee_assessment: "Both providers agree on direction, with a difference in degree.",
      evidence_limitations: ["No independently verified source is attached."],
    },
  ],
  claim_agreements: [
    {
      topic: "Direction of impact",
      claim_ids: ["claim-one"],
      providers: ["openai", "gemini"],
      strength: "high",
      explanation: "Both providers agree.",
    },
  ],
  claim_disagreements: [
    {
      topic: "Scale of impact",
      claim_ids: ["claim-one"],
      positions: [
        { provider: "openai", position: "Limited impact." },
        { provider: "gemini", position: "Broader impact." },
      ],
      disagreement_type: "degree",
      impact_on_verdict: "low",
      referee_resolution: "The scale remains uncertain.",
    },
  ],
  exclusive_contributions: [],
  decisive_factors: [],
};

function mount(props = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <StructuredConclusion
        structured={structured}
        providerStatuses={[
          { provider_name: "OpenAI", provider_status: "LIVE" },
          { provider_name: "Gemini", provider_status: "LIVE" },
          { provider_name: "Mistral", provider_status: "FAILED" },
        ]}
        t={t}
        {...props}
      />
    );
  });
  return {
    container,
    unmount() {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe("Referee Phase C progressive disclosure", () => {
  beforeAll(() => {
    global.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows the executive and completion summaries with real counts", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={structured}
        providerStatuses={[
          { provider_status: "LIVE" },
          { provider_status: "LIVE" },
          { provider_status: "FAILED" },
        ]}
        t={t}
      />
    );
    expect(html).toContain('data-testid="structured-executive-summary"');
    expect(html).toContain('data-testid="summary-claim-count"');
    expect(html).toContain('data-testid="summary-provider-count"');
    expect(html).toContain(">2/3<");
    expect(html).toContain('data-testid="structured-completion-summary"');
    expect(html).toContain("Comparison complete");
  });

  test("opens only the claim matrix by default", () => {
    const view = mount();
    const matrixToggle = view.container.querySelector(
      '[data-testid="structured-claim-matrix-toggle"]'
    );
    const whyToggle = view.container.querySelector(
      '[data-testid="structured-why-verdict-toggle"]'
    );
    const agreementToggle = view.container.querySelector(
      '[data-testid="structured-claim-agreements-toggle"]'
    );
    expect(matrixToggle.getAttribute("aria-expanded")).toBe("true");
    expect(whyToggle.getAttribute("aria-expanded")).toBe("false");
    expect(agreementToggle.getAttribute("aria-expanded")).toBe("false");
    view.unmount();
  });

  test("expands, collapses and closes a section with Escape", () => {
    const view = mount();
    const toggle = view.container.querySelector(
      '[data-testid="structured-why-verdict-toggle"]'
    );
    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle.getAttribute("aria-controls")).toBeTruthy();

    act(() => toggle.click());
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    act(() => {
      toggle.dispatchEvent(new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
      }));
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    view.unmount();
  });

  test("exposes an accessible hover tooltip and click/tap claim details", () => {
    const view = mount();
    const toggle = view.container.querySelector(
      '[data-testid="claim-details-toggle-claim-one"]'
    );
    const tooltip = view.container.querySelector(
      '[data-testid="claim-details-tooltip-claim-one"]'
    );
    const details = view.container.querySelector(
      '[data-testid="claim-details-claim-one"]'
    );

    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle.getAttribute("aria-describedby")).toBe(tooltip.id);
    expect(tooltip.getAttribute("role")).toBe("tooltip");
    expect(tooltip.getAttribute("aria-hidden")).toBe("true");

    act(() => {
      toggle.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    expect(tooltip.getAttribute("aria-hidden")).toBe("false");

    window.innerWidth = 390;
    act(() => toggle.click());
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(details.getAttribute("aria-hidden")).toBe("false");

    act(() => toggle.click());
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(details.getAttribute("aria-hidden")).toBe("true");
    view.unmount();
  });

  test("uses responsive full-width stacks and readable provider states", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion structured={structured} t={t} />
    );
    expect(html).toContain("w-full");
    expect(html).toContain("grid-cols-1");
    expect(html).toContain("md:grid-cols-2");
    expect(html).toContain("xl:grid-cols-3");
    expect(html).toContain("Supports");
    expect(html).toContain("Partially supports");
    expect(html).toContain('role="status"');
  });

  test("keeps legacy conclusions backward compatible", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion legacyText="A saved legacy verdict." t={t} />
    );
    expect(html).toContain('data-conclusion-schema="legacy"');
    expect(html).toContain("A saved legacy verdict.");
    expect(html).not.toContain("structured-executive-summary");
  });
});
