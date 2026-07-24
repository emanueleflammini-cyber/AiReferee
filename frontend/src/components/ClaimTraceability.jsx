import {
  AlertTriangle,
  ExternalLink,
  FileQuestion,
  GitCompareArrows,
  Link2,
  Quote,
  ShieldCheck,
} from "lucide-react";
import { traceabilityViewModel } from "../lib/claimTraceability";

const PROVIDER_LABELS = {
  openai: "ChatGPT",
  gemini: "Gemini",
};

export function ClaimTraceability({
  claims,
  citations,
  claimAnalysisStatus,
  claimAnalysisError,
  providerStatuses,
  executionMode,
  t,
}) {
  const view = traceabilityViewModel({
    claims,
    citations,
    claimAnalysisStatus,
    claimAnalysisError,
    providerStatuses,
    executionMode,
  });

  if (view.kind === "not_available") return null;
  if (view.kind === "failed") {
    return (
      <section
        className="mt-8 border-t border-white/[0.07] pt-7"
        data-testid="claim-traceability-failed"
      >
        <div className="rounded-2xl border border-[#F43F5E]/30 bg-[#F43F5E]/[0.05] p-5">
          <div className="flex items-center gap-2 text-[13px] font-medium text-[#F43F5E]">
            <AlertTriangle className="h-4 w-4" />
            {t("results.traceability.analysisFailed")}
          </div>
          <p className="mt-2 text-[12.5px] leading-relaxed text-white/55">{view.error}</p>
        </div>
      </section>
    );
  }

  const hasContent = (
    view.supported.length
    || view.disputed.length
    || view.weak.length
    || view.citations.length
  );
  if (!hasContent) return null;

  return (
    <section
      className="mt-9 border-t border-white/[0.07] pt-8"
      data-testid="claim-traceability"
    >
      <div className="mb-5">
        <div className="text-[10.5px] uppercase tracking-[0.2em] text-[#00E5FF]/75">
          {t("results.traceability.eyebrow")}
        </div>
        <h3 className="mt-1 text-xl font-semibold text-white">
          {t("results.traceability.title")}
        </h3>
        <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-white/50">
          {t("results.traceability.description")}
        </p>
      </div>

      {view.supported.length > 0 && (
        <TraceSection
          title={t("results.traceability.supportedTitle")}
          icon={ShieldCheck}
          accent="#10B981"
          testId="trace-supported"
        >
          {view.supported.map((claim) => (
            <ClaimCard key={claim.id} claim={claim} t={t} />
          ))}
        </TraceSection>
      )}

      {view.disputed.length > 0 && (
        <TraceSection
          title={t("results.traceability.disputedTitle")}
          icon={GitCompareArrows}
          accent="#F59E0B"
          testId="trace-disputed"
        >
          {view.disputed.map((claim) => (
            <ClaimCard key={claim.id} claim={claim} t={t} disputed />
          ))}
        </TraceSection>
      )}

      {view.citations.length > 0 && (
        <TraceSection
          title={t("results.traceability.sourcesTitle")}
          icon={Link2}
          accent="#00E5FF"
          testId="trace-sources"
        >
          {view.citations.map((citation) => (
            <CitationCard key={citation.id || `${citation.provider}-${citation.rawUrl}`} citation={citation} t={t} />
          ))}
        </TraceSection>
      )}

      {view.weak.length > 0 && (
        <TraceSection
          title={t("results.traceability.weakTitle")}
          icon={FileQuestion}
          accent="#A78BFA"
          testId="trace-weak"
        >
          {view.weak.map((claim) => (
            <ClaimCard key={claim.id} claim={claim} t={t} />
          ))}
        </TraceSection>
      )}
    </section>
  );
}

function TraceSection({ title, icon: Icon, accent, testId, children }) {
  return (
    <section className="mt-7" data-testid={testId}>
      <div className="mb-3 flex items-center gap-2">
        <span
          className="flex h-7 w-7 items-center justify-center rounded-lg border"
          style={{ color: accent, borderColor: `${accent}45`, backgroundColor: `${accent}12` }}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
        <h4 className="text-[15px] font-semibold text-white">{title}</h4>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function ClaimCard({ claim, t, disputed = false }) {
  const providers = [
    ...claim.supportingModels,
    ...claim.disputingModels,
    ...claim.originatingModels,
  ].filter((provider, index, values) => values.indexOf(provider) === index);
  return (
    <article
      className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"
      data-testid={`trace-claim-${claim.id}`}
    >
      <p className="text-[14px] leading-relaxed text-white/85">{claim.text}</p>
      <ProviderChips providers={providers} />
      {disputed && claim.disputingModels.length > 0 && (
        <p className="mt-2 text-[11.5px] text-[#F59E0B]/85">
          {t("results.traceability.disputedBy")}:{" "}
          {claim.disputingModels.map(providerLabel).join(", ")}
        </p>
      )}
      <p className="mt-2 text-[12.5px] leading-relaxed text-white/50">
        {claim.assessment.reason}
      </p>
      {claim.support.length > 0 && (
        <details className="group mt-3 rounded-xl border border-white/[0.06] bg-black/10">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-[12px] text-white/55 hover:text-white/80">
            <Quote className="h-3.5 w-3.5 text-[#00E5FF]/70" />
            {t("results.traceability.showExcerpts")}
          </summary>
          <div className="space-y-3 border-t border-white/[0.06] px-3 py-3">
            {claim.support.map((support, index) => (
              <blockquote key={`${support.provider}-${index}`} className="border-l-2 border-[#00E5FF]/30 pl-3">
                <ProviderChips providers={[support.provider]} compact />
                <p className="mt-2 whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-white/60">
                  “{support.excerpt}”
                </p>
              </blockquote>
            ))}
          </div>
        </details>
      )}
    </article>
  );
}

function CitationCard({ citation, t }) {
  const statusKey = ["unverified", "invalid_url", "missing_url", "verified"].includes(citation.verificationStatus)
    ? citation.verificationStatus
    : "unverified";
  const displayName = citation.title || citation.domain || citation.rawUrl || t("results.traceability.unnamedSource");
  return (
    <article
      className="min-w-0 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"
      data-testid={`trace-citation-${citation.id || "source"}`}
    >
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          {citation.clickableUrl ? (
            <a
              href={citation.clickableUrl}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="inline-flex max-w-full items-start gap-1.5 break-all text-[13.5px] text-[#00E5FF] hover:underline"
            >
              <span className="min-w-0 break-words">{displayName}</span>
              <ExternalLink className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
            </a>
          ) : (
            <div className="break-all text-[13.5px] text-white/75">{displayName}</div>
          )}
          {citation.rawUrl && citation.title && (
            <div className="mt-1 break-all text-[10.5px] text-white/35">{citation.rawUrl}</div>
          )}
        </div>
        <ProviderChips providers={citation.declaredByModels} compact />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <span
          className="rounded-full border border-[#FBBF24]/25 bg-[#FBBF24]/[0.06] px-2 py-0.5 text-[10.5px] text-[#FBBF24]/85"
          data-testid={`citation-status-${statusKey}`}
        >
          {t(`results.traceability.verification.${statusKey}`)}
        </span>
        {citation.extractionMethod && (
          <span className="rounded-full border border-white/10 bg-white/[0.02] px-2 py-0.5 text-[10.5px] text-white/45">
            {t(`results.traceability.extraction.${citation.extractionMethod}`)}
          </span>
        )}
      </div>
    </article>
  );
}

function ProviderChips({ providers, compact = false }) {
  if (!providers?.length) return null;
  return (
    <div className={compact ? "flex flex-wrap gap-1.5" : "mt-3 flex flex-wrap gap-1.5"}>
      {providers.map((provider) => (
        <span
          key={provider}
          className="inline-flex flex-shrink-0 rounded-full border border-white/10 bg-white/[0.035] px-2 py-0.5 text-[10.5px] text-white/60"
        >
          {providerLabel(provider)}
        </span>
      ))}
    </div>
  );
}

function providerLabel(provider) {
  return PROVIDER_LABELS[provider] || provider;
}
