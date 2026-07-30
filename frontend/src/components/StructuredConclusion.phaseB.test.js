import { renderToStaticMarkup } from "react-dom/server";
import { StructuredConclusion } from "./StructuredConclusion";
import { normalizeStructuredConclusion } from "../lib/structuredConclusion";
import en from "../locales/en.json";
import it from "../locales/it.json";


const get = (bundle, path) => (
  path.split(".").reduce((value, key) => value?.[key], bundle)
);
const enT = (key) => get(en, key) ?? key;
const itT = (key) => get(it, key) ?? get(en, key) ?? key;

const base = {
  schema_version: "2.0",
  final_answer: "Structured verdict.",
  agreements: [],
  disagreements: [],
  strongest_evidence: [],
  remaining_uncertainties: [],
  unsupported_claims: [],
  confidence: {
    level: "medium",
    reason: "The available evidence is limited.",
    factors: {
      model_agreement: "medium",
      evidence_quality: "medium",
      uncertainty: "medium",
    },
  },
  referee_reasoning: "",
  what_could_change_the_verdict: [],
  claim_matrix: [],
  claim_agreements: [],
  claim_disagreements: [],
  exclusive_contributions: [],
  decisive_factors: [],
};

const matrixClaim = (overrides = {}) => ({
  claim_id: "claim_one",
  claim: "Automation affects repetitive work.",
  importance: "high",
  provider_positions: [
    {
      provider: "openai",
      display_name: "ChatGPT",
      position: "supports",
      summary: "Routine work is affected first.",
      evidence_refs: ["openai-response"],
      confidence: "high",
    },
    {
      provider: "gemini",
      display_name: "Gemini",
      position: "partially_supports",
      summary: "The effect depends on the task.",
      evidence_refs: ["gemini-response"],
      confidence: "medium",
    },
  ],
  agreement_level: "partial_consensus",
  referee_assessment: "The direction is shared, with a qualification.",
  evidence_limitations: ["No independent source was supplied."],
  ...overrides,
});


describe("Referee 3.0 Phase B rendering", () => {
  test("renders the claim matrix", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{ ...base, claim_matrix: [matrixClaim()] }}
        t={enT}
      />
    );
    expect(html).toContain('data-testid="structured-claim-matrix"');
    expect(html).toContain('data-testid="claim-matrix-claim_one"');
    expect(html).toContain("Automation affects repetitive work.");
  });

  test("renders every provider-position state as text", () => {
    const states = [
      "supports",
      "partially_supports",
      "contradicts",
      "uncertain",
      "not_mentioned",
    ];
    const providerPositions = states.map((position, index) => ({
      provider: `provider-${index}`,
      display_name: `Provider ${index + 1}`,
      position,
      summary: position === "not_mentioned" ? "" : `Summary ${index + 1}`,
      evidence_refs: [],
      confidence: "medium",
    }));
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{
          ...base,
          claim_matrix: [
            matrixClaim({
              provider_positions: providerPositions,
              agreement_level: "unresolved",
            }),
          ],
        }}
        t={enT}
      />
    );
    [
      "Supports",
      "Partially supports",
      "Contradicts",
      "Uncertain",
      "Not mentioned",
    ].forEach((label) => expect(html).toContain(label));
  });

  test("renders structured agreements", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{
          ...base,
          claim_matrix: [matrixClaim()],
          claim_agreements: [
            {
              topic: "Routine automation",
              claim_ids: ["claim_one"],
              providers: ["openai", "gemini"],
              strength: "high",
              explanation: "Both providers support the direction.",
            },
          ],
        }}
        t={enT}
      />
    );
    expect(html).toContain('data-testid="structured-claim-agreements"');
    expect(html).toContain("Routine automation");
    expect(html).toContain("ChatGPT");
    expect(html).toContain("Gemini");
  });

  test("renders structured disagreements", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{
          ...base,
          claim_matrix: [matrixClaim()],
          claim_disagreements: [
            {
              topic: "Scale of replacement",
              claim_ids: ["claim_one"],
              positions: [
                { provider: "openai", position: "Limited replacement." },
                { provider: "gemini", position: "Broad replacement." },
              ],
              disagreement_type: "degree",
              impact_on_verdict: "medium",
              referee_resolution: "The magnitude remains unresolved.",
            },
          ],
        }}
        t={enT}
      />
    );
    expect(html).toContain('data-testid="structured-claim-disagreements"');
    expect(html).toContain("Scale of replacement");
    expect(html).toContain("The magnitude remains unresolved.");
  });

  test("renders exclusive contributions without calling them agreements", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{
          ...base,
          exclusive_contributions: [
            {
              provider: "mistral",
              contribution: "A unique implementation detail.",
              related_claim_ids: [],
              verification_status: "unverified",
              referee_note: "The other providers do not address it.",
            },
          ],
        }}
        t={enT}
      />
    );
    expect(html).toContain(
      'data-testid="structured-exclusive-contributions"'
    );
    expect(html).toContain("A unique implementation detail.");
    expect(html).toContain("Unverified");
  });

  test("renders decisive factors", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{
          ...base,
          decisive_factors: [
            {
              factor: "Shared exact evidence",
              supported_by: ["openai", "gemini"],
              opposed_by: ["mistral"],
              weight: "high",
              explanation: "This evidence determines the verdict.",
            },
          ],
        }}
        t={enT}
      />
    );
    expect(html).toContain('data-testid="structured-decisive-factors"');
    expect(html).toContain("Shared exact evidence");
    expect(html).toContain("Mistral");
  });

  test("keeps all new sections hidden when fields are absent", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion structured={base} t={enT} />
    );
    expect(html).not.toContain("structured-claim-matrix");
    expect(html).not.toContain("structured-claim-agreements");
    expect(html).not.toContain("structured-claim-disagreements");
    expect(html).not.toContain("structured-exclusive-contributions");
    expect(html).not.toContain("structured-decisive-factors");
  });

  test("ignores malformed optional items but keeps valid partial data", () => {
    const normalized = normalizeStructuredConclusion({
      ...base,
      claim_matrix: [
        matrixClaim(),
        { claim_id: "", claim: "", provider_positions: [] },
      ],
      exclusive_contributions: "invalid",
    });
    expect(normalized.claimMatrix).toHaveLength(1);
    expect(normalized.exclusiveContributions).toEqual([]);
  });

  test("uses one-column mobile cards and bounded widths", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{ ...base, claim_matrix: [matrixClaim()] }}
        t={enT}
      />
    );
    expect(html).toContain("grid-cols-1");
    expect(html).toContain("md:grid-cols-2");
    expect(html).toContain("overflow-hidden");
    expect(html).toContain("max-w-full");
  });

  test("provider-position indicators expose accessible labels", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{ ...base, claim_matrix: [matrixClaim()] }}
        t={itT}
      />
    );
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="ChatGPT: Concorda"');
    expect(html).toContain("Concorda in parte");
  });

  test("renders a dynamic provider name without assuming three providers", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{
          ...base,
          claim_matrix: [
            matrixClaim({
              provider_positions: [
                {
                  provider: "future-provider",
                  display_name: "Future Provider",
                  position: "supports",
                  summary: "A future provider supports this.",
                  evidence_refs: [],
                  confidence: "medium",
                },
              ],
              agreement_level: "partial_consensus",
            }),
          ],
        }}
        t={enT}
      />
    );
    expect(html).toContain("Future Provider");
    expect(html).not.toContain("Gemini");
    expect(html).not.toContain("Mistral");
  });

  test("preserves existing Trusted Conclusion sections", () => {
    const html = renderToStaticMarkup(
      <StructuredConclusion
        structured={{
          ...base,
          claim_matrix: [matrixClaim()],
          agreements: [
            {
              id: "legacy-agreement",
              claim: "Existing agreement remains visible.",
              supporting_models: ["openai", "gemini"],
              strength: "strong",
              reason: "Existing evidence.",
              supporting_claim_ids: [],
            },
          ],
          remaining_uncertainties: [
            {
              id: "uncertainty-one",
              description: "An existing uncertainty remains visible.",
              impact: "medium",
            },
          ],
        }}
        t={enT}
      />
    );
    expect(html).toContain('data-testid="structured-claim-matrix"');
    expect(html).toContain('data-testid="structured-agreements"');
    expect(html).toContain('data-testid="structured-uncertainties"');
  });
});
