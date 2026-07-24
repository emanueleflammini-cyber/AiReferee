import { renderToStaticMarkup } from "react-dom/server";
import { StructuredConclusion } from "./StructuredConclusion";
import {
  conclusionViewModel,
  normalizeStructuredConclusion,
  populatedStructuredSections,
} from "../lib/structuredConclusion";

const t = (key) => key;

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
    expect(html).toContain("No usable provider evidence.");
  });

  test("does not invent numeric confidence percentages", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion structured={baseConclusion} t={t} />
    );
    expect(html).not.toMatch(/\b\d{1,3}\s*%/);
    expect(html).not.toContain(">92%<");
    expect(html).not.toContain(">87%<");
  });
});
