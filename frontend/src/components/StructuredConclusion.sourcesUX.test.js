import { act } from "react";
import { createRoot } from "react-dom/client";
import { StructuredConclusion } from "./StructuredConclusion";
import it from "../locales/it.json";
import en from "../locales/en.json";

const get = (bundle, path) => (
  path.split(".").reduce((value, key) => value?.[key], bundle)
);
const makeT = (bundle) => (key) => get(bundle, key) ?? key;

const BASE_STRUCTURED = {
  schema_version: "2.1",
  final_answer: "La risposta sintetizzata rimane sempre visibile.",
  confidence: {
    level: "medium",
    reason: "Due provider concordano sul punto centrale.",
    factors: {
      model_agreement: "high",
      evidence_quality: "medium",
      uncertainty: "low",
    },
  },
  referee_reasoning: "Il Referee ha confrontato accordi, limiti e prove disponibili.",
  agreements: [],
  disagreements: [],
  strongest_evidence: [],
  remaining_uncertainties: [],
  unsupported_claims: [],
  what_could_change_the_verdict: [],
};

// Case A: the synthesizer produced no source_summary entries at all, and no
// provider citation was extracted either — the "no sources" branch.
const STRUCTURED_NO_SOURCES = {
  ...BASE_STRUCTURED,
  source_summary: [],
};

// Case B: at least one source was actually indicated by a model.
const STRUCTURED_WITH_SOURCES = {
  ...BASE_STRUCTURED,
  source_summary: [
    {
      id: "source-web",
      title: "Fonte realmente fornita",
      url: "https://example.com/report",
      publisher: "Example",
      domain: "example.com",
      cited_by: ["openai"],
      supports_claim_ids: [],
      verification_status: "provided_by_model",
    },
  ],
};

function mount(props = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<StructuredConclusion {...props} />);
  });
  return {
    container,
    unmount() {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe.each([
  ["it", it],
  ["en", en],
])("Sources & references — mutually exclusive Case A / Case B (%s)", (_lang, bundle) => {
  const t = makeT(bundle);

  beforeAll(() => {
    global.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("Case A — no sources: shows only the empty-state message, never the unverified notice", () => {
    const view = mount({ structured: STRUCTURED_NO_SOURCES, citations: [], t });
    const panel = view.container.querySelector('[data-testid="sources-disclosure-panel"]');
    const empty = view.container.querySelector('[data-testid="sources-disclosure-empty"]');

    expect(panel).toBeTruthy();
    expect(empty).toBeTruthy();
    expect(empty.textContent).toBe(t("results.structured.noSourcesAvailable"));
    // The Case B disclaimer must not be present anywhere in the panel.
    expect(panel.textContent).not.toContain(t("results.structured.sourcesNotice"));
    // No source category content should be rendered either.
    expect(panel.querySelector('[data-testid^="source-category"]')).toBeFalsy();

    view.unmount();
  });

  test("Case B — sources present: shows the unverified notice and the list, never the empty-state message", () => {
    const view = mount({ structured: STRUCTURED_WITH_SOURCES, citations: [], t });
    const panel = view.container.querySelector('[data-testid="sources-disclosure-panel"]');
    const empty = view.container.querySelector('[data-testid="sources-disclosure-empty"]');

    expect(panel).toBeTruthy();
    expect(empty).toBeFalsy();
    expect(panel.textContent).toContain(t("results.structured.sourcesNotice"));
    expect(panel.textContent).toContain("Fonte realmente fornita");

    view.unmount();
  });

  test("Case A and Case B can never render at the same time", () => {
    const emptyView = mount({ structured: STRUCTURED_NO_SOURCES, citations: [], t });
    const emptyPanel = emptyView.container.querySelector('[data-testid="sources-disclosure-panel"]');
    const hasEmptyState = !!emptyPanel.querySelector('[data-testid="sources-disclosure-empty"]');
    const hasNoticeInEmptyState = emptyPanel.textContent.includes(t("results.structured.sourcesNotice"));
    emptyView.unmount();

    const fullView = mount({ structured: STRUCTURED_WITH_SOURCES, citations: [], t });
    const fullPanel = fullView.container.querySelector('[data-testid="sources-disclosure-panel"]');
    const hasEmptyStateInFull = !!fullPanel.querySelector('[data-testid="sources-disclosure-empty"]');
    const hasNoticeInFull = fullPanel.textContent.includes(t("results.structured.sourcesNotice"));
    fullView.unmount();

    // Case A: empty-state message present, notice absent.
    expect(hasEmptyState && !hasNoticeInEmptyState).toBe(true);
    // Case B: notice present, empty-state message absent.
    expect(hasNoticeInFull && !hasEmptyStateInFull).toBe(true);
  });
});
