import {
  AlertTriangle,
  Check,
  ExternalLink,
  GitCompareArrows,
  HelpCircle,
  Link2,
  Quote,
  Scale,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import {
  conclusionEvidenceViewModel,
  conclusionViewModel,
} from "../lib/structuredConclusion";
import { translateEnum } from "../lib/resultPresentation";
import { SafeAnswerText } from "./SafeAnswerText";

const PROVIDER_LABELS = {
  openai: "ChatGPT",
  gemini: "Gemini",
  mistral: "Mistral",
};

export function StructuredConclusion({
  structured,
  legacyText,
  synthesisStatus,
  synthesisError,
  claims = [],
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
          {t("results.errors.conclusionUnavailable")}
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

  const evidenceView = conclusionEvidenceViewModel({ structured, claims });
  const conclusion = evidenceView.conclusion;
  return (
    <div
      data-testid="trusted-conclusion-structured"
      data-conclusion-schema={conclusion.schema_version}
    >
      <div className="mb-3 text-[11px] uppercase tracking-[0.2em] text-[#00E5FF]/80">
        {t("results.structured.finalVerdict")}
      </div>
      <SafeAnswerText
        text={conclusion.final_verdict}
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

      {evidenceView.keyFindings.length > 0 && (
        <ConclusionSection
          title={t("results.structured.keyFindings")}
          subtitle={t("results.structured.keyFindingsDescription")}
          icon={ShieldCheck}
          accent="#00E5FF"
          testId="structured-key-findings"
        >
          {evidenceView.keyFindings.map((finding) => (
            <KeyFindingCard key={finding.id} finding={finding} t={t} />
          ))}
        </ConclusionSection>
      )}

      {evidenceView.sharedFacts.length > 0 && (
        <ConclusionSection
          title={t("results.structured.sharedFacts")}
          icon={ShieldCheck}
          accent="#10B981"
          testId="structured-shared-facts"
        >
          {evidenceView.sharedFacts.map((claim) => (
            <ClaimArticle key={claim.id} text={claim.text}>
              <ClaimEvidenceDetails claims={[claim]} t={t} />
            </ClaimArticle>
          ))}
        </ConclusionSection>
      )}

      {evidenceView.agreements.length > 0 && (
        <ConclusionSection
          title={t("results.structured.agreements")}
          icon={Check}
          accent="#10B981"
          testId="structured-agreements"
        >
          {evidenceView.agreements.map((agreement) => (
            <ClaimArticle key={agreement.id} text={agreement.claim}>
              <div className="flex flex-wrap items-center gap-2">
                <StrengthBadge value={agreement.strength} t={t} />
              </div>
              <ClaimEvidenceDetails
                claims={agreement.linkedClaims}
                fallbackSupporting={agreement.supporting_models}
                t={t}
              />
              {agreement.reason && (
                <p className="mt-3 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]">
                  {agreement.reason}
                </p>
              )}
            </ClaimArticle>
          ))}
        </ConclusionSection>
      )}

      {evidenceView.disagreements.length > 0 && (
        <ConclusionSection
          title={t("results.structured.disagreements")}
          icon={GitCompareArrows}
          accent="#F59E0B"
          testId="structured-disagreements"
        >
          <div
            className="min-w-0 max-w-full rounded-xl border border-[#F59E0B]/20 bg-[#F59E0B]/[0.035] p-4"
            data-testid="structured-disagreement-explanation"
          >
            <h4 className="break-words text-[14px] font-semibold text-white/90 [overflow-wrap:anywhere]">
              {t("results.structured.disagreementWhy")}
            </h4>
            <p className="mt-1 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]">
              {t("results.structured.disagreementDescription")}
            </p>
          </div>
          {evidenceView.disagreements.map((disagreement) => (
            <article key={disagreement.id} className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <div className="text-[10.5px] uppercase tracking-[0.18em] text-[#F59E0B]/80">
                {t("results.structured.contestedPoint")}
              </div>
              <div className="mt-1 break-words text-[14px] font-medium leading-relaxed text-white/85 [overflow-wrap:anywhere]">
                {disagreement.topic}
              </div>
              <div className="mt-4 space-y-3">
                {disagreement.positions.map((position, index) => (
                  <ProviderPosition
                    key={`${position.model}-${index}`}
                    position={position}
                    fallbackClaims={disagreement.linkedClaims}
                    t={t}
                  />
                ))}
              </div>
              {disagreement.referee_assessment && (
                <LabeledParagraph
                  label={t("results.structured.refereeReasoning")}
                  text={disagreement.referee_assessment}
                />
              )}
              {disagreement.missing_information && (
                <LabeledParagraph
                  label={t("results.structured.missingInformation")}
                  text={disagreement.missing_information}
                />
              )}
            </article>
          ))}
        </ConclusionSection>
      )}

      {evidenceView.strongestEvidence.length > 0 && (
        <ConclusionSection
          title={t("results.structured.strongestEvidence")}
          icon={ShieldCheck}
          accent="#00E5FF"
          testId="structured-evidence"
        >
          {evidenceView.strongestEvidence.map((evidence) => (
            <ClaimArticle key={evidence.id} text={evidence.claim}>
              {evidence.description && (
                <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">
                  {evidence.description}
                </p>
              )}
              <ClaimEvidenceDetails
                claims={evidence.linkedClaims}
                fallbackSupporting={evidence.supporting_models}
                t={t}
              />
              <div className="mt-3">
                <span className="max-w-full break-words rounded-full border border-[#00E5FF]/25 bg-[#00E5FF]/[0.06] px-2 py-0.5 text-[10.5px] text-[#00E5FF]/80 [overflow-wrap:anywhere]">
                  {translateEnum(t, "results.structured.sourceStatus", evidence.source_status)}
                </span>
              </div>
            </ClaimArticle>
          ))}
        </ConclusionSection>
      )}

      {conclusion.uncertainties.length > 0 && (
        <ConclusionSection
          title={t("results.structured.remainingUncertainties")}
          icon={HelpCircle}
          accent="#A78BFA"
          testId="structured-uncertainties"
        >
          {conclusion.uncertainties.map((uncertainty) => (
            <article key={uncertainty.id} className="flex min-w-0 max-w-full flex-col items-start gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 sm:flex-row sm:justify-between">
              <p className="min-w-0 break-words text-[13.5px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">{uncertainty.description}</p>
              <ImpactBadge value={uncertainty.impact} t={t} />
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.referee_reasoning && (
        <ConclusionSection
          title={t("results.structured.refereeReasoning")}
          icon={Scale}
          accent="#00E5FF"
          testId="structured-referee-reasoning"
        >
          <p className="break-words text-[13.5px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">
            {conclusion.referee_reasoning}
          </p>
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

      {conclusion.provider_assessment.length > 0 && (
        <ConclusionSection
          title={t("results.structured.providerAssessment")}
          subtitle={t("results.structured.providerAssessmentDescription")}
          icon={Scale}
          accent="#A78BFA"
          testId="structured-provider-assessment"
        >
          {conclusion.provider_assessment.map((assessment) => (
            <ProviderAssessmentCard
              key={assessment.provider}
              assessment={assessment}
              t={t}
            />
          ))}
        </ConclusionSection>
      )}

      {conclusion.source_summary.length > 0 && (
        <ConclusionSection
          title={t("results.structured.sources")}
          subtitle={t("results.structured.sourcesNotice")}
          icon={Link2}
          accent="#00E5FF"
          testId="structured-sources"
        >
          {conclusion.source_summary.map((source) => (
            <SourceSummaryCard key={source.id} source={source} t={t} />
          ))}
        </ConclusionSection>
      )}

      {conclusion.what_could_change.length > 0 && (
        <ConclusionSection
          title={t("results.structured.whatCouldChange")}
          icon={Scale}
          accent="#0066FF"
          testId="structured-change-factors"
        >
          <ul className="space-y-2">
            {conclusion.what_could_change.map((item, index) => (
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

function KeyFindingCard({ finding, t }) {
  return (
    <article
      className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
      data-testid={`structured-finding-${finding.id}`}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <FindingStatusBadge value={finding.status} t={t} />
        <StrengthBadge value={finding.evidenceStrength} t={t} />
      </div>
      <p className="mt-3 break-words text-[14px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">
        {finding.claim}
      </p>
      {finding.explanation && (
        <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]">
          {finding.explanation}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        {finding.supportingProviders.length > 0 && (
          <ProviderMeta
            label={t("results.structured.supportedBy")}
            providers={finding.supportingProviders}
          />
        )}
        {finding.dissentingProviders.length > 0 && (
          <ProviderMeta
            label={t("results.structured.disputedBy")}
            providers={finding.dissentingProviders}
          />
        )}
      </div>
      {finding.relevantExcerpts.length > 0 && (
        <ExcerptList excerpts={finding.relevantExcerpts} t={t} />
      )}
      {finding.sources.length > 0 && (
        <div className="mt-3 border-t border-white/[0.06] pt-3">
          <div className="mb-2 text-[10.5px] uppercase tracking-[0.14em] text-white/40">
            {t("results.structured.associatedSources")}
          </div>
          <div className="flex min-w-0 flex-wrap gap-2">
            {finding.sources.map((source) => (
              <SourceInlineLink key={source.id} source={source} t={t} />
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

function ProviderAssessmentCard({ assessment, t }) {
  return (
    <article className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <ProviderChip provider={assessment.provider} />
        <FactorBadge
          label={t("results.structured.perceivedAccuracy")}
          value={assessment.perceivedAccuracy}
          prefix="results.structured.assessmentLevel"
          t={t}
        />
        <FactorBadge
          label={t("results.structured.coherence")}
          value={assessment.coherence}
          prefix="results.structured.assessmentLevel"
          t={t}
        />
      </div>
      {assessment.usefulContributions.length > 0 && (
        <TextList
          title={t("results.structured.usefulContributions")}
          values={assessment.usefulContributions}
          accent="#10B981"
        />
      )}
      {assessment.weaknesses.length > 0 && (
        <TextList
          title={t("results.structured.providerWeaknesses")}
          values={assessment.weaknesses}
          accent="#F59E0B"
        />
      )}
    </article>
  );
}

function SourceSummaryCard({ source, t }) {
  return (
    <article
      className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
      data-testid={`structured-source-${source.id}`}
    >
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <SourceInlineLink source={source} t={t} />
          {source.rawUrl && source.title && (
            <div className="mt-1 max-w-full truncate text-[10.5px] text-white/35" title={source.rawUrl}>
              {source.rawUrl}
            </div>
          )}
        </div>
        <ProviderChips providers={source.citedBy} compact />
      </div>
      <div className="mt-3">
        <span className="inline-flex max-w-full break-words rounded-full border border-[#FBBF24]/25 bg-[#FBBF24]/[0.06] px-2 py-0.5 text-[10.5px] text-[#FBBF24]/85 [overflow-wrap:anywhere]">
          {translateEnum(
            t,
            "results.structured.sourceVerification",
            source.verificationStatus
          )}
        </span>
      </div>
    </article>
  );
}

function SourceInlineLink({ source, t }) {
  const displayName = source.title
    || source.publisher
    || source.domain
    || source.rawUrl
    || t("results.structured.unnamedSource");
  if (!source.clickableUrl) {
    return (
      <span className="max-w-full break-words text-[12.5px] text-white/65 [overflow-wrap:anywhere]">
        {displayName}
      </span>
    );
  }
  return (
    <a
      href={source.clickableUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex max-w-full items-start gap-1.5 break-words text-[12.5px] text-[#00E5FF] hover:underline focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120] [overflow-wrap:anywhere]"
      aria-label={t("results.structured.openSource", { source: displayName })}
    >
      <span className="min-w-0 break-words [overflow-wrap:anywhere]">{displayName}</span>
      <ExternalLink className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
    </a>
  );
}

function TextList({ title, values, accent }) {
  return (
    <div className="mt-3 border-t border-white/[0.06] pt-3">
      <div className="text-[10.5px] uppercase tracking-[0.14em] text-white/40">{title}</div>
      <ul className="mt-2 space-y-1.5">
        {values.map((value, index) => (
          <li key={`${value}-${index}`} className="flex min-w-0 gap-2 text-[12.5px] leading-relaxed text-white/60">
            <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ backgroundColor: accent }} />
            <span className="min-w-0 break-words [overflow-wrap:anywhere]">{value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ClaimArticle({ text, children }) {
  return (
    <article className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
      <p className="break-words text-[14px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">{text}</p>
      {children}
    </article>
  );
}

function ClaimEvidenceDetails({
  claims = [],
  fallbackSupporting = [],
  fallbackDisputing = [],
  t,
}) {
  const supporting = uniqueProviders([
    ...fallbackSupporting,
    ...claims.flatMap((claim) => claim.supportingModels || []),
    ...claims.flatMap((claim) => (claim.support || []).map((item) => item.provider)),
  ]);
  const disputing = uniqueProviders([
    ...fallbackDisputing,
    ...claims.flatMap((claim) => claim.disputingModels || []),
    ...claims.flatMap((claim) => (claim.dispute || []).map((item) => item.provider)),
  ]);
  const excerpts = uniqueExcerpts(claims.flatMap((claim) => [
    ...(claim.support || []).map((item) => ({ ...item, stance: "support" })),
    ...(claim.dispute || []).map((item) => ({ ...item, stance: "dispute" })),
  ]));
  const consensusLevel = disputing.length > 0
    ? "low"
    : supporting.length >= 2
      ? "high"
      : supporting.length === 1
        ? "medium"
        : "low";

  if (!supporting.length && !disputing.length && !excerpts.length) return null;
  return (
    <div className="mt-3 border-t border-white/[0.06] pt-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {supporting.length > 0 && (
          <ProviderMeta label={t("results.structured.supportedBy")} providers={supporting} />
        )}
        {disputing.length > 0 && (
          <ProviderMeta label={t("results.structured.disputedBy")} providers={disputing} />
        )}
        <span className="text-[11px] text-white/45">
          {t("results.structured.consensusLevel")}:{" "}
          <strong className="font-medium text-white/70">
            {translateEnum(t, "results.structured.level", consensusLevel)}
          </strong>
        </span>
      </div>
      {excerpts.length > 0 && <ExcerptList excerpts={excerpts} t={t} />}
    </div>
  );
}

function ProviderMeta({ label, providers }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      <span className="text-[11px] text-white/45">{label}:</span>
      <ProviderChips providers={providers} compact />
    </div>
  );
}

function ProviderPosition({ position, fallbackClaims, t }) {
  const provider = position.model;
  const linkedClaims = position.linkedClaims?.length
    ? position.linkedClaims
    : (fallbackClaims || []).filter((claim) => (
      claim.originatingModels?.includes(provider)
      || claim.supportingModels?.includes(provider)
      || claim.disputingModels?.includes(provider)
    ));
  const evidence = uniqueExcerpts(linkedClaims.flatMap((claim) => [
    ...(claim.support || []),
    ...(claim.dispute || []),
  ]).filter((item) => item.provider === provider));

  return (
    <div className="min-w-0 rounded-xl border border-white/[0.06] bg-black/10 p-3">
      <div className="flex min-w-0 flex-col items-start gap-2 sm:flex-row sm:gap-3">
        <ProviderChip provider={provider} />
        <p className="min-w-0 break-words text-[13px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">
          {position.position}
        </p>
      </div>
      {evidence.length > 0 && (
        <div className="mt-3">
          <div className="text-[10.5px] uppercase tracking-[0.14em] text-white/40">
            {t("results.structured.evidenceUsed")}
          </div>
          <ExcerptList excerpts={evidence} t={t} />
        </div>
      )}
    </div>
  );
}

function ExcerptList({ excerpts, t }) {
  return (
    <details className="group mt-3 min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-black/10">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-xl px-3 py-2.5 text-[12px] text-white/55 hover:text-white/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120]">
        <Quote className="h-3.5 w-3.5 flex-shrink-0 text-[#00E5FF]/70" aria-hidden="true" />
        {t("results.structured.relevantExcerpts")}
      </summary>
      <div className="space-y-3 border-t border-white/[0.06] px-3 py-3">
        {excerpts.map((excerpt, index) => (
          <blockquote
            key={`${excerpt.provider}-${excerpt.excerpt}-${index}`}
            className={`min-w-0 max-w-full border-l-2 pl-3 ${
              excerpt.stance === "dispute" ? "border-[#F59E0B]/45" : "border-[#00E5FF]/30"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <ProviderChip provider={excerpt.provider} />
              {excerpt.stance === "dispute" && (
                <span className="text-[10.5px] text-[#F59E0B]/80">
                  {t("results.structured.contraryExcerpt")}
                </span>
              )}
            </div>
            <p className="mt-2 whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-white/60 [overflow-wrap:anywhere]">
              “{excerpt.excerpt}”
            </p>
          </blockquote>
        ))}
      </div>
    </details>
  );
}

function LabeledParagraph({ label, text }) {
  return (
    <div className="mt-3 border-t border-white/[0.06] pt-3">
      <div className="text-[10.5px] uppercase tracking-[0.14em] text-white/40">{label}</div>
      <p className="mt-1 break-words text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">{text}</p>
    </div>
  );
}

function ConclusionSection({ title, subtitle, icon: Icon, accent, testId, children }) {
  return (
    <section className="mt-8 min-w-0 max-w-full border-t border-white/[0.07] pt-7" data-testid={testId}>
      <div className="mb-4">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="flex h-7 w-7 items-center justify-center rounded-lg border"
            style={{ color: accent, borderColor: `${accent}45`, backgroundColor: `${accent}12` }}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <h3 className="min-w-0 break-words text-[15px] font-semibold text-white [overflow-wrap:anywhere]">{title}</h3>
        </div>
        {subtitle && (
          <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/45 [overflow-wrap:anywhere]">
            {subtitle}
          </p>
        )}
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

function FactorBadge({
  label,
  value,
  t,
  prefix = "results.structured.level",
}) {
  return (
    <span className="max-w-full break-words rounded-full border border-white/10 bg-white/[0.025] px-2.5 py-1 text-[10.5px] text-white/55 [overflow-wrap:anywhere]">
      {label}: <strong className="font-medium text-white/80">{translateEnum(t, prefix, value)}</strong>
    </span>
  );
}

function FindingStatusBadge({ value, t }) {
  const color = value === "probable" || value === "verified"
    ? "#10B981"
    : value === "disputed"
      ? "#F59E0B"
      : value === "unsupported"
        ? "#F43F5E"
        : "#A78BFA";
  return (
    <span
      className="flex-shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide"
      style={{
        color,
        borderColor: `${color}45`,
        backgroundColor: `${color}12`,
      }}
    >
      {translateEnum(t, "results.structured.findingStatus", value)}
    </span>
  );
}

function StrengthBadge({ value, t }) {
  return (
    <span className="flex-shrink-0 rounded-full border border-[#10B981]/25 bg-[#10B981]/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-wide text-[#10B981]">
      {translateEnum(t, "results.structured.strength", value)}
    </span>
  );
}

function ImpactBadge({ value, t }) {
  return (
    <span className="flex-shrink-0 rounded-full border border-[#A78BFA]/25 bg-[#A78BFA]/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-wide text-[#A78BFA]">
      {translateEnum(t, "results.structured.impact", value)}
    </span>
  );
}

function uniqueProviders(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function uniqueExcerpts(values) {
  const seen = new Set();
  return (values || []).filter((item) => {
    if (!item?.provider || !item?.excerpt) return false;
    const key = `${item.provider}:${item.excerpt}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function confidenceStyle(level) {
  const color = level === "high" ? "#10B981" : level === "medium" ? "#F59E0B" : "#F43F5E";
  return {
    borderColor: `${color}45`,
    backgroundColor: `${color}0d`,
  };
}
