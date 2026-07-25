import { renderToStaticMarkup } from "react-dom/server";
import { StructuredConclusion } from "./StructuredConclusion";
import {
  conclusionViewModel,
  normalizeStructuredConclusion,
  populatedStructuredSections,
} from "../lib/structuredConclusion";
import en from "../locales/en.json";
import it from "../locales/it.json";

const t = (key) => key;
const get = (bundle, path) => path.split(".").reduce((value, key) => value?.[key], bundle);
const itT = (key) => get(it, key) ?? get(en, key) ?? key;

const baseConclusion = {
  schema_version: "2.0",
  final_answer: "Combined answer",
  agreements: [],
  disagreements: [],
  strongest_evidence: [],
  remaining_uncertainties: [],
  unsupported_claims: [],
  confidence: {
    level: "medium",
    reason: "Evidence is limited to the current provider panel.",
    factors: {
      model_agreement: "medium",
      evidence_quality: "medium",
      uncertainty: "medium",
    },
  },
  what_could_change_the_verdict: [],
};

describe("Trusted Conclusion 2.0 rendering", () => {
  test("normalizes a structured conclusion without inventing optional sections", () => {
    const normalized = normalizeStructuredConclusion(baseConclusion);
    expect(normalized.final_answer).toBe("Combined answer");
    expect(populatedStructuredSections(baseConclusion)).toEqual([]);
  });

  test("renders only populated structured sections", () => {
    const structured = {
      ...baseConclusion,
      agreements: [
        {
          id: "a1",
          claim: "Shared claim",
          supporting_models: ["openai", "gemini"],
          strength: "strong",
          reason: "Both providers state it.",
        },
      ],
      remaining_uncertainties: [
        { id: "u1", description: "A current source is missing.", impact: "high" },
      ],
    };
    const html = renderToStaticMarkup(
      <StructuredConclusion structured={structured} t={t} />
    );
    expect(html).toContain("data-testid=\"trusted-conclusion-structured\"");
    expect(html).toContain("data-testid=\"structured-agreements\"");
    expect(html).toContain("data-testid=\"structured-uncertainties\"");
    expect(html).not.toContain("data-testid=\"structured-disagreements\"");
    expect(html).not.toContain("data-testid=\"structured-unsupported\"");
  });

  test("renders legacy records visibly as legacy", () => {
    const view = conclusionViewModel({ legacyText: "Legacy conclusion" });
    expect(view.kind).toBe("legacy");
    const html = renderToStaticMarkup(
      <StructuredConclusion legacyText="Legacy conclusion" t={t} />
    );
    expect(html).toContain("data-conclusion-schema=\"legacy\"");
    expect(html).toContain("Legacy conclusion");
  });

  test("renders synthesis failure explicitly instead of blank content", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        synthesisStatus="FAILED"
        synthesisError="No usable provider evidence."
        t={t}
      />
    );
    expect(html).toContain("data-conclusion-schema=\"failed\"");
    expect(html).toContain("results.errors.conclusionUnavailable");
  });

  test("does not invent numeric confidence percentages", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion structured={baseConclusion} t={t} />
    );
    expect(html).not.toMatch(/\b\d{1,3}\s*%/);
    expect(html).not.toContain(">92%<");
    expect(html).not.toContain(">87%<");
  });

  test("maps evidence strength in Italian without exposing the raw enum", () => {
    const structured = {
      ...baseConclusion,
      agreements: [
        {
          id: "a1",
          claim: "Affermazione condivisa",
          supporting_models: ["openai", "gemini"],
          strength: "strong",
          reason: "Entrambi i provider la sostengono.",
        },
      ],
    };
    const html = renderToStaticMarkup(
      <StructuredConclusion structured={structured} t={itT} />
    );
    expect(html).toContain("Evidenza forte");
    expect(html).not.toContain("VALORE NON RICONOSCIUTO");
    expect(html).not.toMatch(/>STRONG</);
  });

  test("renders shared facts with providers, consensus and exact excerpts", () => {
    const claims = [
      {
        id: "claim_shared",
        text: "La cache riduce il lavoro ripetuto.",
        claim_type: "fact",
        originating_models: ["openai", "gemini"],
        supporting_models: ["openai", "gemini"],
        disputing_models: [],
        support: [
          { provider: "openai", response_excerpt: "La cache riduce il lavoro ripetuto." },
          { provider: "gemini", response_excerpt: "La cache riduce il lavoro ripetuto." },
        ],
        assessment: { status: "supported", reason: "Confermato da entrambi." },
      },
    ];
    const html = renderToStaticMarkup(
      <StructuredConclusion structured={baseConclusion} claims={claims} t={itT} />
    );
    expect(html).toContain("data-testid=\"structured-shared-facts\"");
    expect(html).toContain("Fatti condivisi");
    expect(html).toContain("ChatGPT");
    expect(html).toContain("Gemini");
    expect(html).toContain("Livello di consenso");
    expect(html).toContain("La cache riduce il lavoro ripetuto.");
  });

  test("shows disagreement explanation only for genuinely different positions", () => {
    const real = {
      ...baseConclusion,
      disagreements: [
        {
          id: "d1",
          topic: "Limite attuale",
          positions: [
            { model: "openai", position: "Il limite è dieci." },
            { model: "gemini", position: "Il limite è venti." },
          ],
          referee_assessment: "Le risposte confliggono.",
          missing_information: "Una fonte ufficiale aggiornata.",
        },
      ],
    };
    const fake = {
      ...baseConclusion,
      disagreements: [
        {
          id: "d2",
          topic: "Nessun conflitto reale",
          positions: [
            { model: "openai", position: "Stessa posizione." },
            { model: "gemini", position: "Stessa posizione." },
          ],
          referee_assessment: "Le risposte coincidono.",
        },
      ],
    };
    const realHtml = renderToStaticMarkup(
      <StructuredConclusion structured={real} t={itT} />
    );
    const fakeHtml = renderToStaticMarkup(
      <StructuredConclusion structured={fake} t={itT} />
    );
    expect(realHtml).toContain("Punti di disaccordo");
    expect(realHtml).toContain("Perché i modelli non sono d&#x27;accordo?");
    expect(realHtml).toContain("Una fonte ufficiale aggiornata.");
    expect(fakeHtml).not.toContain("data-testid=\"structured-disagreements\"");
  });
});
