import {
  AlertTriangle,
  Check,
  GitCompareArrows,
  HelpCircle,
  Scale,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { conclusionViewModel } from "../lib/structuredConclusion";
import { translateEnum } from "../lib/resultPresentation";
import { SafeAnswerText } from "./SafeAnswerText";

const PROVIDER_LABELS = {
  openai: "ChatGPT",
  gemini: "Gemini",
};

export function StructuredConclusion({
  structured,
  legacyText,
  synthesisStatus,
  synthesisError,
  t,
}) {
  const view = conclusionViewModel({
    structured,
    legacyText,
    synthesisStatus,
    synthesisError,
  });

  if (view.kind === "failed") {
    return (
      <div
        className="min-w-0 max-w-full rounded-2xl border border-[#F43F5E]/35 bg-[#F43F5E]/[0.06] p-4 sm:p-5"
        data-testid="trusted-conclusion-failed"
        data-conclusion-schema="failed"
        role="alert"
      >
        <div className="flex items-center gap-2 text-[#F43F5E] font-medium">
          <AlertTriangle className="w-4 h-4" />
          {t("results.structured.synthesisFailed")}
        </div>
        <p className="mt-2 break-words text-[13.5px] leading-relaxed text-white/65 [overflow-wrap:anywhere]">
          {view.error}
        </p>
      </div>
    );
  }

  if (view.kind === "legacy") {
    return (
      <div data-testid="trusted-conclusion-legacy" data-conclusion-schema="legacy">
        <div className="mb-3 inline-flex rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10.5px] uppercase tracking-[0.16em] text-white/45">
          {t("results.structured.legacy")}
        </div>
        <SafeAnswerText
          text={view.legacyText}
          className="text-[15.5px] leading-[1.75] text-white/85"
          testId="legacy-conclusion-text"
        />
      </div>
    );
  }

  const conclusion = view.conclusion;
  return (
    <div data-testid="trusted-conclusion-structured" data-conclusion-schema="2.0">
      <SafeAnswerText
        text={conclusion.final_answer}
        className="text-[15.5px] md:text-[16.5px] leading-[1.75] text-white/90"
        testId="structured-final-answer"
      />

      <div className="mt-7 grid grid-cols-1 md:grid-cols-[180px_1fr] gap-4">
        <div
          className="min-w-0 rounded-2xl border p-4"
          style={confidenceStyle(conclusion.confidence.level)}
          data-testid="structured-confidence"
        >
          <div className="text-[10.5px] uppercase tracking-[0.2em] text-white/45">
            {t("results.structured.confidence")}
          </div>
          <div className="mt-2 text-xl font-semibold capitalize text-white">
            {translateEnum(t, "results.structured.level", conclusion.confidence.level)}
          </div>
        </div>
        <div className="min-w-0 rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-[#00E5FF]/80">
            <Scale className="w-3.5 h-3.5" />
            {t("results.structured.whyVerdict")}
          </div>
          <p className="mt-2 break-words text-[13.5px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">
            {conclusion.confidence.reason}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <FactorBadge
              label={t("results.structured.modelAgreement")}
              value={conclusion.confidence.factors.model_agreement}
              t={t}
            />
            <FactorBadge
              label={t("results.structured.evidenceQuality")}
              value={conclusion.confidence.factors.evidence_quality}
              t={t}
            />
            <FactorBadge
              label={t("results.structured.uncertainty")}
              value={conclusion.confidence.factors.uncertainty}
              t={t}
            />
          </div>
        </div>
      </div>

      {conclusion.agreements.length > 0 && (
        <ConclusionSection
          title={t("results.structured.agreements")}
          icon={Check}
          accent="#10B981"
          testId="structured-agreements"
        >
          {conclusion.agreements.map((agreement) => (
            <article key={agreement.id} className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <div className="flex min-w-0 flex-col items-start gap-3 sm:flex-row sm:justify-between">
                <p className="min-w-0 break-words text-[14px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">{agreement.claim}</p>
                <StrengthBadge value={agreement.strength} t={t} />
              </div>
              <ProviderChips providers={agreement.supporting_models} />
              <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]">{agreement.reason}</p>
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.disagreements.length > 0 && (
        <ConclusionSection
          title={t("results.structured.disagreements")}
          icon={GitCompareArrows}
          accent="#F59E0B"
          testId="structured-disagreements"
        >
          {conclusion.disagreements.map((disagreement) => (
            <article key={disagreement.id} className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <div className="break-words text-[11px] uppercase tracking-[0.18em] text-white/45 [overflow-wrap:anywhere]">{disagreement.topic}</div>
              <div className="mt-3 space-y-2">
                {disagreement.positions.map((position, index) => (
                  <div key={`${position.model}-${index}`} className="flex min-w-0 flex-col items-start gap-2 sm:flex-row sm:gap-3">
                    <ProviderChip provider={position.model} />
                    <p className="min-w-0 break-words text-[13px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">{position.position}</p>
                  </div>
                ))}
              </div>
              <p className="mt-3 break-words border-t border-white/[0.06] pt-3 text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">
                {disagreement.referee_assessment}
              </p>
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.strongest_evidence.length > 0 && (
        <ConclusionSection
          title={t("results.structured.strongestEvidence")}
          icon={ShieldCheck}
          accent="#00E5FF"
          testId="structured-evidence"
        >
          {conclusion.strongest_evidence.map((evidence) => (
            <article key={evidence.id} className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <p className="break-words text-[14px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">{evidence.claim}</p>
              <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">{evidence.description}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <ProviderChips providers={evidence.supporting_models} compact />
                <span className="max-w-full break-words rounded-full border border-[#00E5FF]/25 bg-[#00E5FF]/[0.06] px-2 py-0.5 text-[10.5px] text-[#00E5FF]/80 [overflow-wrap:anywhere]">
                  {translateEnum(t, "results.structured.sourceStatus", evidence.source_status)}
                </span>
              </div>
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.remaining_uncertainties.length > 0 && (
        <ConclusionSection
          title={t("results.structured.remainingUncertainties")}
          icon={HelpCircle}
          accent="#A78BFA"
          testId="structured-uncertainties"
        >
          {conclusion.remaining_uncertainties.map((uncertainty) => (
            <article key={uncertainty.id} className="flex min-w-0 max-w-full flex-col items-start gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 sm:flex-row sm:justify-between">
              <p className="min-w-0 break-words text-[13.5px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">{uncertainty.description}</p>
              <ImpactBadge value={uncertainty.impact} t={t} />
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.unsupported_claims.length > 0 && (
        <ConclusionSection
          title={t("results.structured.unsupportedClaims")}
          icon={ShieldAlert}
          accent="#F43F5E"
          testId="structured-unsupported"
        >
          {conclusion.unsupported_claims.map((claim) => (
            <article key={claim.id} className="min-w-0 max-w-full rounded-xl border border-[#F43F5E]/15 bg-[#F43F5E]/[0.025] p-4">
              <p className="break-words text-[13.5px] leading-relaxed text-white/80 [overflow-wrap:anywhere]">{claim.claim}</p>
              <ProviderChips providers={claim.originating_models} />
              <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]">{claim.reason}</p>
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.what_could_change_the_verdict.length > 0 && (
        <ConclusionSection
          title={t("results.structured.whatCouldChange")}
          icon={Scale}
          accent="#0066FF"
          testId="structured-change-factors"
        >
          <ul className="space-y-2">
            {conclusion.what_could_change_the_verdict.map((item, index) => (
              <li key={index} className="flex min-w-0 gap-2 text-[13.5px] leading-relaxed text-white/70">
                <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-[#0066FF]" />
                <span className="min-w-0 break-words [overflow-wrap:anywhere]">{item}</span>
              </li>
            ))}
          </ul>
        </ConclusionSection>
      )}
    </div>
  );
}

function ConclusionSection({ title, icon: Icon, accent, testId, children }) {
  return (
    <section className="mt-8 min-w-0 max-w-full border-t border-white/[0.07] pt-7" data-testid={testId}>
      <div className="mb-4 flex min-w-0 items-center gap-2">
        <span
          className="flex h-7 w-7 items-center justify-center rounded-lg border"
          style={{ color: accent, borderColor: `${accent}45`, backgroundColor: `${accent}12` }}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <h3 className="min-w-0 break-words text-[15px] font-semibold text-white [overflow-wrap:anywhere]">{title}</h3>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function ProviderChips({ providers, compact = false }) {
  if (!providers?.length) return null;
  return (
    <div className={compact ? "flex min-w-0 max-w-full flex-wrap gap-1.5" : "mt-3 flex min-w-0 max-w-full flex-wrap gap-1.5"}>
      {providers.map((provider) => <ProviderChip key={provider} provider={provider} />)}
    </div>
  );
}

function ProviderChip({ provider }) {
  return (
    <span className="inline-flex max-w-full break-words rounded-full border border-white/10 bg-white/[0.035] px-2 py-0.5 text-[10.5px] text-white/60 [overflow-wrap:anywhere]">
      {PROVIDER_LABELS[provider] || provider}
    </span>
  );
}

function FactorBadge({ label, value, t }) {
  return (
    <span className="max-w-full break-words rounded-full border border-white/10 bg-white/[0.025] px-2.5 py-1 text-[10.5px] text-white/55 [overflow-wrap:anywhere]">
      {label}: <strong className="font-medium text-white/80">{translateEnum(t, "results.structured.level", value)}</strong>
    </span>
  );
}

function StrengthBadge({ value, t }) {
  return (
    <span className="flex-shrink-0 rounded-full border border-[#10B981]/25 bg-[#10B981]/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-wide text-[#10B981]">
      {translateEnum(t, "results.structured.level", value)}
    </span>
  );
}

function ImpactBadge({ value, t }) {
  return (
    <span className="flex-shrink-0 rounded-full border border-[#A78BFA]/25 bg-[#A78BFA]/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-wide text-[#A78BFA]">
      {translateEnum(t, "results.structured.level", value)}
    </span>
  );
}

function confidenceStyle(level) {
  const color = level === "high" ? "#10B981" : level === "medium" ? "#F59E0B" : "#F43F5E";
  return {
    borderColor: `${color}45`,
    backgroundColor: `${color}0d`,
  };
}
