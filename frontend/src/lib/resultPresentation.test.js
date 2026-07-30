import en from "../locales/en.json";
import it from "../locales/it.json";
import { localizeProviderError, translateEnum } from "./resultPresentation";

function get(bundle, path) {
  return path.split(".").reduce((value, key) => value?.[key], bundle);
}

function translator(bundle) {
  return (key, variables) => {
    let value = get(bundle, key);
    if (value == null) value = get(en, key);
    if (value == null) return key;
    return Object.entries(variables || {}).reduce(
      (result, [name, replacement]) => result.replaceAll(`{${name}}`, replacement),
      value,
    );
  };
}

describe("Results localization presentation", () => {
  const enT = translator(en);
  const itT = translator(it);

  test("Italian Results labels do not fall back to known English static labels", () => {
    const keys = [
      "results.evidenceMeter",
      "results.consensusEvolution",
      "results.trustedConclusion",
      "results.structured.finalVerdict",
      "results.structured.sharedFacts",
      "results.structured.disagreementWhy",
      "results.structured.refereeReasoning",
      "results.structured.whatCouldChange",
      "results.traceability.title",
      "results.traceability.disputedTitle",
      "results.traceability.sourcesTitle",
      "results.traceability.weakTitle",
      "results.errors.providerUnavailable",
      "results.retry",
      "results.shareVerdict",
      "results.evolutionSteps.challenge.title",
      "debate.backResults",
      "reuse.previousQuestion",
    ];
    keys.forEach((key) => {
      expect(itT(key)).not.toBe(key);
      expect(itT(key)).not.toBe(enT(key));
    });
  });

  test("English Results page uses English labels", () => {
    expect(enT("results.evidenceMeter")).toBe("Evidence Meter");
    expect(enT("results.consensusEvolution")).toBe("Consensus Evolution");
    expect(enT("results.errors.providerUnavailable")).toBe("Provider unavailable");
  });

  test("Italian provider states do not expose raw execution enums", () => {
    expect(itT("results.status.demo")).toBe("Demo");
    expect(itT("results.status.live")).toBe("Attivo");
    expect(itT("results.status.failed")).toBe("Non disponibile");
    expect(itT("results.status.timeout")).toBe("Tempo scaduto");
    expect(itT("results.status.disabled")).toBe("Disattivato");
    expect(itT("results.status.mock")).toBe("Simulato");
    expect(itT("results.status.liveCount", { n: 3 })).toBe("Provider attivi: 3");
  });

  test("Italian Results uses the requested evidence terminology", () => {
    expect(itT("results.evidenceMeter")).toBe("Indicatore delle prove");
    expect(itT("results.evidenceTitle")).toBe("Quanto è affidabile questa conclusione?");
    expect(itT("results.structured.strongestEvidence")).toBe("Prova condivisa più solida");
    expect(itT("results.structured.relevantExcerpts")).toBe("Mostra gli estratti testuali rilevanti");
  });

  test("known provider errors are presented in Italian without changing the API payload", () => {
    expect(localizeProviderError(
      itT,
      "it",
      "Gemini API key is not configured.",
      "FAILED",
    )).toBe("La chiave API del provider non è configurata.");
    expect(localizeProviderError(
      itT,
      "it",
      "Network Error",
      "FAILED",
    )).toBe("Non è stato possibile raggiungere il provider. Controlla la connessione e riprova.");
    expect(localizeProviderError(
      itT,
      "it",
      "request timed out",
      "TIMEOUT",
    )).toBe("Tempo massimo del provider superato");
  });

  test("English provider errors preserve the original technical reason", () => {
    expect(localizeProviderError(
      enT,
      "en",
      "OpenAI rate limit / quota exceeded.",
      "FAILED",
    )).toBe("OpenAI rate limit / quota exceeded.");
  });

  test("known enum labels are localized", () => {
    expect(translateEnum(itT, "results.structured.level", "high")).toBe("Alta");
    expect(translateEnum(enT, "results.structured.level", "high")).toBe("High");
    expect(translateEnum(itT, "results.structured.strength", "strong")).toBe("Evidenza forte");
    expect(translateEnum(itT, "results.structured.strength", "moderate")).toBe("Evidenza media");
    expect(translateEnum(itT, "results.structured.strength", "weak")).toBe("Evidenza debole");
    expect(translateEnum(itT, "results.structured.impact", "high")).toBe("Impatto alto");
  });

  test("unknown enum values use a readable safe fallback", () => {
    expect(translateEnum(itT, "results.structured.level", "experimental_value")).toBe(
      "Valore non riconosciuto (experimental value)",
    );
    expect(translateEnum(enT, "results.structured.level", "experimental_value")).toBe(
      "Unknown (experimental value)",
    );
  });
});
