import { act } from "react";
import { createRoot } from "react-dom/client";
import { StructuredConclusion } from "./StructuredConclusion";
import it from "../locales/it.json";

const get = (bundle, path) => (
  path.split(".").reduce((value, key) => value?.[key], bundle)
);
const t = (key) => get(it, key) ?? key;

const structured = {
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
  agreements: [
    {
      id: "agreement-1",
      claim: "Punto condiviso.",
      supporting_models: ["openai", "gemini"],
      strength: "strong",
      reason: "Entrambi i provider lo sostengono.",
    },
  ],
  disagreements: [],
  strongest_evidence: [],
  remaining_uncertainties: [],
  unsupported_claims: [],
  what_could_change_the_verdict: ["Una nuova fonte ufficiale."],
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
    root.render(<StructuredConclusion structured={structured} t={t} {...props} />);
  });
  return {
    container,
    unmount() {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe("Super Answer disclosure controls", () => {
  beforeAll(() => {
    global.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("starts with both independent sections closed and the answer visible", () => {
    const view = mount();
    const reasoningToggle = view.container.querySelector('[data-testid="reasoning-disclosure-toggle"]');
    const sourcesToggle = view.container.querySelector('[data-testid="sources-disclosure-toggle"]');
    const reasoningPanel = view.container.querySelector('[data-testid="reasoning-disclosure-panel"]');
    const sourcesPanel = view.container.querySelector('[data-testid="sources-disclosure-panel"]');

    expect(view.container.querySelector('[data-testid="structured-final-answer"]')).toBeTruthy();
    expect(reasoningToggle.tagName).toBe("BUTTON");
    expect(sourcesToggle.tagName).toBe("BUTTON");
    expect(reasoningToggle.getAttribute("aria-expanded")).toBe("false");
    expect(sourcesToggle.getAttribute("aria-expanded")).toBe("false");
    expect(reasoningToggle.getAttribute("aria-controls")).toBe(reasoningPanel.id);
    expect(sourcesToggle.getAttribute("aria-controls")).toBe(sourcesPanel.id);
    expect(reasoningPanel.hidden).toBe(true);
    expect(sourcesPanel.hidden).toBe(true);
    view.unmount();
  });

  test("opens both sections together and changes both button labels", () => {
    const view = mount();
    const reasoningToggle = view.container.querySelector('[data-testid="reasoning-disclosure-toggle"]');
    const sourcesToggle = view.container.querySelector('[data-testid="sources-disclosure-toggle"]');

    act(() => reasoningToggle.click());
    act(() => sourcesToggle.click());

    expect(reasoningToggle.getAttribute("aria-expanded")).toBe("true");
    expect(sourcesToggle.getAttribute("aria-expanded")).toBe("true");
    expect(reasoningToggle.textContent).toBe("🧠 Nascondi il ragionamento");
    expect(sourcesToggle.textContent).toBe("🔗 Nascondi fonti e riferimenti");
    expect(view.container.querySelector('[data-testid="reasoning-disclosure-panel"]').hidden).toBe(false);
    expect(view.container.querySelector('[data-testid="sources-disclosure-panel"]').hidden).toBe(false);
    view.unmount();
  });

  test("closing reasoning does not close sources", () => {
    const view = mount();
    const reasoningToggle = view.container.querySelector('[data-testid="reasoning-disclosure-toggle"]');
    const sourcesToggle = view.container.querySelector('[data-testid="sources-disclosure-toggle"]');

    act(() => reasoningToggle.click());
    act(() => sourcesToggle.click());
    act(() => reasoningToggle.click());

    expect(reasoningToggle.getAttribute("aria-expanded")).toBe("false");
    expect(sourcesToggle.getAttribute("aria-expanded")).toBe("true");
    expect(reasoningToggle.textContent).toBe("🧠 Mostra il ragionamento");
    expect(sourcesToggle.textContent).toBe("🔗 Nascondi fonti e riferimenti");
    view.unmount();
  });

  test("shows only populated source categories and never invents references", () => {
    const view = mount();
    const sourcesToggle = view.container.querySelector('[data-testid="sources-disclosure-toggle"]');
    act(() => sourcesToggle.click());

    const panel = view.container.querySelector('[data-testid="sources-disclosure-panel"]');
    expect(panel.textContent).toContain("Fonti web");
    expect(panel.textContent).toContain("Fonte realmente fornita");
    expect(panel.textContent).not.toContain("Documentazione ufficiale");
    expect(panel.textContent).not.toContain("Studi e pubblicazioni");
    expect(panel.textContent).not.toContain("Bibliografia");
    expect(panel.textContent).not.toContain("DOI:");
    expect(panel.textContent).not.toContain("PubMed");
    expect(panel.textContent).not.toContain("arXiv");
    expect(panel.textContent).not.toContain("Autore inventato");
    view.unmount();
  });

  test("renders no empty category when no source exists", () => {
    const view = mount({
      structured: { ...structured, source_summary: [] },
      citations: [],
    });
    const sourcesToggle = view.container.querySelector('[data-testid="sources-disclosure-toggle"]');
    act(() => sourcesToggle.click());

    expect(view.container.querySelectorAll('[data-testid="source-category"]')).toHaveLength(0);
    expect(view.container.querySelector('[data-testid="sources-disclosure-empty"]')).toBeTruthy();
    view.unmount();
  });

  test.each([360, 390, 768, 1280])(
    "keeps the disclosure controls within the viewport at %d px",
    (width) => {
      window.innerWidth = width;
      const view = mount();
      const controls = view.container.querySelector('[data-testid="conclusion-disclosure-controls"]');
      const buttons = controls.querySelectorAll("button");

      expect(controls.className).toContain("min-w-0");
      expect(controls.className).toContain("grid-cols-1");
      expect(controls.className).toContain("min-[370px]:grid-cols-2");
      buttons.forEach((button) => {
        expect(button.className).toContain("min-w-0");
        expect(button.className).toContain("w-full");
        expect(button.querySelector("span").className).toContain("whitespace-nowrap");
      });
      view.unmount();
    }
  );
});
