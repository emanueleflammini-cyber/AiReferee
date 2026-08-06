import fs from "fs";
import path from "path";
import { renderToStaticMarkup } from "react-dom/server";
import { StructuredConclusion } from "../components/StructuredConclusion";
import { MODELS, MODEL_STATUS } from "../lib/mockData";

const source = (relativePath) => fs.readFileSync(path.join(__dirname, "..", relativePath), "utf8");
const t = (key) => key;

describe("Phase 4 responsive and compatibility safeguards", () => {
  test("provider cards use one column below 768px and preserve the desktop grid", () => {
    const results = source("pages/Results.jsx");
    expect(results).toContain("grid min-w-0 grid-cols-1 gap-5 md:grid-cols-2");
    expect(results).not.toContain("grid-cols-2 md:grid-cols-2");
  });

  test("cards and citation blocks avoid fixed overflowing widths", () => {
    const results = source("pages/Results.jsx");
    const traceability = source("components/ClaimTraceability.jsx");
    expect(results).toContain("min-w-0 max-w-full");
    expect(traceability).toContain("[overflow-wrap:anywhere]");
    expect(traceability).not.toContain("break-all");
  });

  test("long model labels have flexible wrapping instead of narrow fixed columns", () => {
    const results = source("pages/Results.jsx");
    expect(results).toContain("break-words text-[14.5px]");
    expect(results).toContain("[overflow-wrap:anywhere]");
  });

  test("mobile controls retain accessible tap targets and expand state", () => {
    const results = source("pages/Results.jsx");
    expect(results).toContain("min-h-11");
    expect(results).toContain("aria-expanded={open}");
    expect(results).toContain("aria-controls={`details-${m.id}`}");
  });

  test("Share Verdict remains present", () => {
    const results = source("pages/Results.jsx");
    expect(results).toContain('data-testid="share-verdict-button"');
    expect(results).toContain('aria-label={t("results.shareVerdict")}');
  });

  test("Mistral is an active card while Grok and Claude remain upcoming", () => {
    const mistral = MODELS.find((model) => model.id === "model-e");
    const grok = MODELS.find((model) => model.id === "model-d");
    const claude = MODELS.find((model) => model.id === "model-b");
    expect(mistral.status).toBe(MODEL_STATUS.LIVE);
    expect(grok.status).toBe(MODEL_STATUS.COMING_SOON);
    expect(claude.status).toBe(MODEL_STATUS.PREMIUM_COMING_SOON);
  });

  test("Results uses the backend model name for active provider cards", () => {
    const results = source("pages/Results.jsx");
    expect(results).toContain("codename={live?.codename || m.codename}");
    expect(results).toContain("modelUsed={live?.model_used}");
  });

  test("Results forwards 2.1 citations to the Super Answer disclosures", () => {
    const results = source("pages/Results.jsx");
    expect(results).toContain("citations={citations}");
    expect(results).not.toContain("<ClaimTraceability");
  });

  test("legacy generated content is not translated or replaced on the client", () => {
    const original = "Legacy provider content stays exactly in English.";
    const html = renderToStaticMarkup(
      <StructuredConclusion legacyText={original} t={t} />,
    );
    expect(html).toContain(original);
  });
});
