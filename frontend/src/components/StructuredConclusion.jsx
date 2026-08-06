import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  CircleMinus,
  ExternalLink,
  GitCompareArrows,
  HelpCircle,
  Info,
  Link2,
  Quote,
  Scale,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useId, useState } from "react";
import {
  conclusionEvidenceViewModel,
  conclusionViewModel,
} from "../lib/structuredConclusion";
import { safeHttpUrl } from "../lib/claimTraceability";
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
  citations = [],
  providerStatuses = [],
  t,
}) {
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const reasoningId = useId();
  const sourcesId = useId();
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
  const metrics = conclusionMetrics({
    conclusion,
    evidenceView,
    claims,
    providerStatuses,
  });
  const sourceGroups = sourceGroupsForDisclosure({
    structuredSources: conclusion.source_summary,
    citations,
  });
  const hasSources = sourceGroups.some((group) => group.sources.length > 0);
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

      <div
        className="mt-6 grid min-w-0 grid-cols-1 gap-2 min-[370px]:grid-cols-2 sm:gap-3"
        data-testid="conclusion-disclosure-controls"
      >
        <DisclosureButton
          open={reasoningOpen}
          onClick={() => setReasoningOpen((value) => !value)}
          controls={reasoningId}
          testId="reasoning-disclosure-toggle"
        >
          {reasoningOpen
            ? t("results.structured.hideReasoning")
            : t("results.structured.showReasoning")}
        </DisclosureButton>
        <DisclosureButton
          open={sourcesOpen}
          onClick={() => setSourcesOpen((value) => !value)}
          controls={sourcesId}
          testId="sources-disclosure-toggle"
        >
          {sourcesOpen
            ? t("results.structured.hideSourcesAndReferences")
            : t("results.structured.showSourcesAndReferences")}
        </DisclosureButton>
      </div>

      <div
        id={reasoningId}
        className="min-w-0 max-w-full"
        data-testid="reasoning-disclosure-panel"
        hidden={!reasoningOpen}
      >
          <ExecutiveSummary
            conclusion={conclusion}
            metrics={metrics}
            t={t}
          />
      <ConclusionSection
        title={t("results.structured.whyVerdict")}
        icon={Scale}
        accent="#00E5FF"
        testId="structured-why-verdict"
      >
        <p className="break-words text-[13.5px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">
          {conclusion.confidence.reason}
        </p>
        <div className="flex flex-wrap gap-2">
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
      </ConclusionSection>

      {conclusion.claimMatrix.length > 0 && (
        <ConclusionSection
          title={t("results.structured.claimMatrix")}
          subtitle={t("results.structured.claimMatrixDescription")}
          icon={GitCompareArrows}
          accent="#00E5FF"
          testId="structured-claim-matrix"
          defaultOpen
        >
          {conclusion.claimMatrix.map((claim) => (
            <ClaimMatrixCard key={claim.claimId} claim={claim} t={t} />
          ))}
        </ConclusionSection>
      )}

      {conclusion.claimAgreements.length > 0 && (
        <ConclusionSection
          title={t("results.structured.mainAgreements")}
          icon={Check}
          accent="#10B981"
          testId="structured-claim-agreements"
        >
          {conclusion.claimAgreements.map((agreement, index) => (
            <article
              key={`${agreement.topic}-${index}`}
              className="min-w-0 max-w-full rounded-xl border border-[#10B981]/15 bg-[#10B981]/[0.025] p-4"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <LevelBadge
                  label={t("results.structured.agreementStrength")}
                  value={agreement.strength}
                  t={t}
                />
                <ProviderChips providers={agreement.providers} compact />
              </div>
              <p className="mt-3 break-words text-[14px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">
                {agreement.topic}
              </p>
              <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">
                {agreement.explanation}
              </p>
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.claimDisagreements.length > 0 && (
        <ConclusionSection
          title={t("results.structured.mainDisagreements")}
          subtitle={t("results.structured.disagreementDescription")}
          icon={GitCompareArrows}
          accent="#F59E0B"
          testId="structured-claim-disagreements"
        >
          {conclusion.claimDisagreements.map((disagreement, index) => (
            <StructuredDisagreementCard
              key={`${disagreement.topic}-${index}`}
              disagreement={disagreement}
              t={t}
            />
          ))}
        </ConclusionSection>
      )}

      {conclusion.exclusiveContributions.length > 0 && (
        <ConclusionSection
          title={t("results.structured.exclusiveContributions")}
          subtitle={t("results.structured.exclusiveContributionsDescription")}
          icon={ShieldCheck}
          accent="#A78BFA"
          testId="structured-exclusive-contributions"
        >
          {conclusion.exclusiveContributions.map((contribution, index) => (
            <article
              key={`${contribution.provider}-${index}`}
              className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <ProviderChip provider={contribution.provider} />
                <EnumBadge
                  prefix="results.structured.verificationStatus"
                  value={contribution.verificationStatus}
                  t={t}
                />
              </div>
              <p className="mt-3 break-words text-[14px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">
                {contribution.contribution}
              </p>
              <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">
                {contribution.refereeNote}
              </p>
            </article>
          ))}
        </ConclusionSection>
      )}

      {conclusion.decisiveFactors.length > 0 && (
        <ConclusionSection
          title={t("results.structured.decisiveFactors")}
          subtitle={t("results.structured.decisiveFactorsDescription")}
          icon={Scale}
          accent="#0066FF"
          testId="structured-decisive-factors"
        >
          {conclusion.decisiveFactors.map((factor, index) => (
            <article
              key={`${factor.factor}-${index}`}
              className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
            >
              <LevelBadge
                label={t("results.structured.weight")}
                value={factor.weight}
                t={t}
              />
              <p className="mt-3 break-words text-[14px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">
                {factor.factor}
              </p>
              <div className="mt-3 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
                {factor.supportedBy.length > 0 && (
                  <ProviderMeta
                    label={t("results.structured.supportedBy")}
                    providers={factor.supportedBy}
                  />
                )}
                {factor.opposedBy.length > 0 && (
                  <ProviderMeta
                    label={t("results.structured.disputedBy")}
                    providers={factor.opposedBy}
                  />
                )}
              </div>
              <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">
                {factor.explanation}
              </p>
            </article>
          ))}
        </ConclusionSection>
      )}

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

      <CompletionSummary metrics={metrics} conclusion={conclusion} t={t} />
      </div>

      <section
        id={sourcesId}
        className="mt-7 min-w-0 max-w-full border-t border-white/[0.07] pt-7"
        data-testid="sources-disclosure-panel"
        hidden={!sourcesOpen}
      >
          <div className="mb-5">
            <h3 className="break-words text-lg font-semibold text-white [overflow-wrap:anywhere]">
              {t("results.structured.sourcesAndReferences")}
            </h3>
            <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]">
              {t("results.structured.sourcesNotice")}
            </p>
          </div>
          {hasSources ? (
            <div className="space-y-7">
              {sourceGroups.map((group) => (
                group.sources.length > 0 && (
                  <SourceCategory
                    key={group.key}
                    title={t(`results.structured.sourceCategories.${group.key}`)}
                    sources={group.sources}
                    t={t}
                  />
                )
              ))}
            </div>
          ) : (
            <p
              className="break-words text-[13px] leading-relaxed text-white/50 [overflow-wrap:anywhere]"
              data-testid="sources-disclosure-empty"
            >
              {t("results.structured.noSourcesAvailable")}
            </p>
          )}
      </section>
    </div>
  );
}

function DisclosureButton({ open, onClick, controls, testId, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      aria-controls={controls}
      data-testid={testId}
      className="inline-flex min-h-11 min-w-0 w-full items-center justify-center rounded-xl border border-[#00E5FF]/25 bg-[#00E5FF]/[0.055] px-2.5 py-2 text-center text-[11px] font-medium leading-tight text-[#00E5FF] transition-colors hover:bg-[#00E5FF]/[0.1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120] min-[370px]:px-1.5 min-[370px]:text-[10px] min-[430px]:px-3 min-[430px]:text-[11px] sm:px-4 sm:text-[13px]"
    >
      <span className="whitespace-nowrap">{children}</span>
    </button>
  );
}

function SourceCategory({ title, sources, t }) {
  return (
    <section className="min-w-0 max-w-full" data-testid="source-category">
      <div className="mb-3 flex min-w-0 items-center gap-2">
        <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg border border-[#00E5FF]/30 bg-[#00E5FF]/[0.06] text-[#00E5FF]">
          <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <h4 className="min-w-0 break-words text-[15px] font-semibold text-white [overflow-wrap:anywhere]">
          {title}
        </h4>
      </div>
      <div className="space-y-3">
        {sources.map((source) => (
          <SourceSummaryCard key={source.id} source={source} t={t} />
        ))}
      </div>
    </section>
  );
}

function sourceGroupsForDisclosure({ structuredSources, citations }) {
  const seen = new Set();
  const sources = [];
  const addSource = (source) => {
    const rawUrl = String(source?.rawUrl || source?.url || "").trim();
    const id = String(source?.id || rawUrl).trim();
    const title = String(source?.title || "").trim();
    if (!id || (!title && !rawUrl)) return;
    const key = rawUrl || id;
    if (seen.has(key)) return;
    seen.add(key);
    sources.push({
      id,
      title,
      rawUrl,
      clickableUrl: source?.clickableUrl || safeHttpUrl(rawUrl),
      publisher: String(source?.publisher || "").trim(),
      domain: String(source?.domain || "").trim(),
      citedBy: Array.isArray(source?.citedBy)
        ? source.citedBy
        : (Array.isArray(source?.declared_by_models) ? source.declared_by_models : []),
      verificationStatus: String(
        source?.verificationStatus || source?.verification_status || "unverified"
      ).trim(),
      sourceType: String(source?.sourceType || source?.source_type || "").toLowerCase(),
    });
  };

  (Array.isArray(structuredSources) ? structuredSources : []).forEach(addSource);
  (Array.isArray(citations) ? citations : []).forEach(addSource);

  const groups = {
    web: [],
    official: [],
    studies: [],
    bibliography: [],
  };
  sources.forEach((source) => {
    const type = source.sourceType;
    if (/(book|chapter|bibliograph)/u.test(type)) {
      groups.bibliography.push(source);
    } else if (/(study|publication|journal|scientific|doi|pubmed|arxiv)/u.test(type)) {
      groups.studies.push(source);
    } else if (/(official|documentation|docs)/u.test(type)) {
      groups.official.push(source);
    } else {
      groups.web.push(source);
    }
  });
  return [
    { key: "web", sources: groups.web },
    { key: "official", sources: groups.official },
    { key: "studies", sources: groups.studies },
    { key: "bibliography", sources: groups.bibliography },
  ];
}

function ExecutiveSummary({ conclusion, metrics, t }) {
  return (
    <section
      className="mt-6 min-w-0 max-w-full rounded-2xl border border-[#00E5FF]/20 bg-[#00E5FF]/[0.035] p-4 sm:p-5"
      data-testid="structured-executive-summary"
      aria-labelledby="structured-executive-summary-title"
    >
      <div
        id="structured-executive-summary-title"
        className="text-[11px] uppercase tracking-[0.2em] text-[#00E5FF]/80"
      >
        {t("results.structured.executiveSummary")}
      </div>
      <div className="mt-3 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <SummaryMetric
          label={t("results.structured.summaryVerdict")}
          value={conclusion.final_verdict}
          wide
          testId="summary-verdict"
        />
        <SummaryMetric
          label={t("results.structured.confidence")}
          value={translateEnum(t, "results.structured.level", conclusion.confidence.level)}
          testId="summary-confidence"
        />
        <SummaryMetric
          label={t("results.structured.claimCount")}
          value={metrics.claimCount}
          testId="summary-claim-count"
        />
        <SummaryMetric
          label={t("results.structured.agreementCount")}
          value={metrics.agreementCount}
          testId="summary-agreement-count"
        />
        <SummaryMetric
          label={t("results.structured.disagreementCount")}
          value={metrics.disagreementCount}
          testId="summary-disagreement-count"
        />
        <SummaryMetric
          label={t("results.structured.liveProvidersUsed")}
          value={`${metrics.liveProviders}/${metrics.totalProviders}`}
          testId="summary-provider-count"
        />
      </div>
    </section>
  );
}

function SummaryMetric({ label, value, wide = false, testId }) {
  return (
    <div
      className={`min-w-0 rounded-xl border border-white/[0.07] bg-black/10 px-3 py-3 ${
        wide ? "sm:col-span-2 lg:col-span-3" : ""
      }`}
      data-testid={testId}
    >
      <div className="text-[10px] uppercase tracking-[0.16em] text-white/40">
        {label}
      </div>
      <div
        className={`mt-1 min-w-0 break-words text-white/85 [overflow-wrap:anywhere] ${
          wide ? "line-clamp-2 text-[13px] leading-relaxed" : "text-[17px] font-semibold"
        }`}
        title={typeof value === "string" ? value : undefined}
      >
        {value}
      </div>
    </div>
  );
}

function CompletionSummary({ metrics, conclusion, t }) {
  return (
    <section
      className="mt-10 min-w-0 max-w-full rounded-2xl border border-[#10B981]/20 bg-[#10B981]/[0.035] p-4 sm:p-5"
      data-testid="structured-completion-summary"
      aria-labelledby="structured-completion-summary-title"
    >
      <div className="flex min-w-0 items-center gap-2 text-[#10B981]">
        <ShieldCheck className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
        <h3 id="structured-completion-summary-title" className="text-[13px] font-semibold">
          {t("results.structured.comparisonComplete")}
        </h3>
      </div>
      <dl className="mt-4 grid min-w-0 grid-cols-2 gap-3 md:grid-cols-5">
        <CompletionMetric
          label={t("results.structured.providersAnalyzed")}
          value={`${metrics.liveProviders}/${metrics.totalProviders}`}
        />
        <CompletionMetric label={t("results.structured.claimCount")} value={metrics.claimCount} />
        <CompletionMetric label={t("results.structured.agreementCount")} value={metrics.agreementCount} />
        <CompletionMetric label={t("results.structured.disagreementCount")} value={metrics.disagreementCount} />
        <CompletionMetric
          label={t("results.structured.finalConfidence")}
          value={translateEnum(t, "results.structured.level", conclusion.confidence.level)}
        />
      </dl>
    </section>
  );
}

function CompletionMetric({ label, value }) {
  return (
    <div className="min-w-0 rounded-xl border border-white/[0.06] bg-black/10 px-3 py-3">
      <dt className="break-words text-[10px] uppercase tracking-[0.12em] text-white/40 [overflow-wrap:anywhere]">
        {label}
      </dt>
      <dd className="mt-1 text-[15px] font-semibold text-white/80">{value}</dd>
    </div>
  );
}

function conclusionMetrics({ conclusion, evidenceView, claims, providerStatuses }) {
  const matrixClaims = conclusion.claimMatrix.length;
  const findingClaims = evidenceView.keyFindings.length;
  const fallbackClaims = Array.isArray(claims) ? claims.length : 0;
  const claimCount = matrixClaims || findingClaims || fallbackClaims;
  const agreementCount = conclusion.claimAgreements.length
    || evidenceView.agreements.length
    || evidenceView.sharedFacts.length;
  const disagreementCount = conclusion.claimDisagreements.length
    || evidenceView.disagreements.length;

  const statuses = (Array.isArray(providerStatuses) ? providerStatuses : [])
    .map((item) => String(
      typeof item === "string"
        ? item
        : item?.provider_status || item?.status || ""
    ).toUpperCase())
    .filter((status) => ["LIVE", "FAILED", "TIMEOUT", "MOCK"].includes(status));
  const providersFromMatrix = new Set(
    conclusion.claimMatrix.flatMap((claim) => (
      claim.providerPositions.map((position) => position.provider)
    ))
  ).size;
  const liveProviders = statuses.length
    ? statuses.filter((status) => status === "LIVE").length
    : providersFromMatrix;
  const totalProviders = statuses.length || providersFromMatrix;

  return {
    claimCount,
    agreementCount,
    disagreementCount,
    liveProviders,
    totalProviders,
  };
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

function ClaimMatrixCard({ claim, t }) {
  const [open, setOpen] = useState(false);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const detailsId = useId();
  const tooltipId = useId();
  const toggleDetails = () => setOpen((value) => !value);

  return (
    <article
      className="w-full min-w-0 max-w-full overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.02] p-4 sm:p-5"
      data-testid={`claim-matrix-${claim.claimId}`}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <LevelBadge
          label={t("results.structured.importance")}
          value={claim.importance}
          t={t}
        />
        <EnumBadge
          prefix="results.structured.agreementLevel"
          value={claim.agreementLevel}
          t={t}
        />
      </div>
      <p className="mt-3 break-words text-[14px] leading-relaxed text-white/90 [overflow-wrap:anywhere]">
        {claim.claim}
      </p>
      <div
        className="mt-4 flex min-w-0 max-w-full flex-wrap gap-2"
        data-testid="claim-matrix-provider-summary"
      >
        {claim.providerPositions.map((position) => (
          <ProviderPositionBadge
            key={position.provider}
            position={position}
            t={t}
          />
        ))}
      </div>

      <div className="relative mt-4 inline-flex max-w-full">
        <button
          type="button"
          className="inline-flex min-h-11 max-w-full items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-[12.5px] text-white/70 transition-colors duration-200 hover:border-[#00E5FF]/35 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120]"
          aria-label={open
            ? t("results.structured.closeClaimDetails")
            : t("results.structured.openClaimDetails")}
          aria-expanded={open}
          aria-controls={detailsId}
          aria-describedby={tooltipId}
          onClick={toggleDetails}
          onMouseEnter={() => setTooltipVisible(true)}
          onMouseLeave={() => setTooltipVisible(false)}
          onFocus={() => setTooltipVisible(true)}
          onBlur={() => setTooltipVisible(false)}
          data-testid={`claim-details-toggle-${claim.claimId}`}
        >
          <Info className="h-4 w-4 flex-shrink-0 text-[#00E5FF]" aria-hidden="true" />
          <span>{open
            ? t("results.structured.hideDetails")
            : t("results.structured.details")}</span>
          {open
            ? <ChevronDown className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
            : <ChevronRight className="h-4 w-4 flex-shrink-0" aria-hidden="true" />}
        </button>
        <span
          id={tooltipId}
          role="tooltip"
          aria-hidden={!tooltipVisible}
          className={`pointer-events-none absolute bottom-[calc(100%+8px)] left-0 z-20 w-64 max-w-[calc(100vw-3rem)] rounded-lg border border-white/10 bg-[#111827] px-3 py-2 text-[11.5px] leading-relaxed text-white/75 shadow-xl transition-opacity duration-200 ${
            tooltipVisible ? "opacity-100" : "opacity-0"
          }`}
          data-testid={`claim-details-tooltip-${claim.claimId}`}
        >
          {t("results.structured.claimDetailsTooltip")}
        </span>
      </div>

      <div
        id={detailsId}
        role="region"
        aria-label={t("results.structured.claimDetailsRegion")}
        aria-hidden={!open}
        inert={!open}
        className={`grid transition-[grid-template-rows,opacity,margin] duration-200 ease-out ${
          open
            ? "mt-4 grid-rows-[1fr] opacity-100"
            : "mt-0 grid-rows-[0fr] opacity-0"
        }`}
        data-testid={`claim-details-${claim.claimId}`}
      >
        <div className="min-h-0 overflow-hidden">
          <div
            className="grid w-full min-w-0 grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3"
            data-testid="claim-matrix-provider-grid"
          >
            {claim.providerPositions.map((position) => (
              <MatrixProviderPosition
                key={position.provider}
                position={position}
                t={t}
              />
            ))}
          </div>
          {claim.refereeAssessment && (
            <LabeledParagraph
              label={t("results.structured.refereeAssessment")}
              text={claim.refereeAssessment}
              expandable
              t={t}
            />
          )}
          {claim.evidenceLimitations.length > 0 && (
            <TextList
              title={t("results.structured.evidenceLimitations")}
              values={claim.evidenceLimitations}
              accent="#F59E0B"
            />
          )}
        </div>
      </div>
    </article>
  );
}

function ProviderPositionBadge({ position, t }) {
  const state = providerPositionState(position.position);
  const Icon = state.icon;
  const statusText = translateEnum(
    t,
    "results.structured.providerPosition",
    position.position
  );
  return (
    <span
      className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]"
      style={{
        color: state.color,
        borderColor: `${state.color}45`,
        backgroundColor: `${state.color}12`,
      }}
      role="status"
      aria-label={`${position.displayName}: ${statusText}`}
    >
      <span className="min-w-0 truncate text-white/75">
        {position.displayName || PROVIDER_LABELS[position.provider] || position.provider}
      </span>
      <Icon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
      <span className="sr-only">{statusText}</span>
    </span>
  );
}

function MatrixProviderPosition({ position, t }) {
  const state = providerPositionState(position.position);
  const Icon = state.icon;
  const statusText = translateEnum(
    t,
    "results.structured.providerPosition",
    position.position
  );
  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden rounded-xl border border-white/[0.06] bg-black/10 p-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <ProviderChip
          provider={position.provider}
          displayName={position.displayName}
        />
        <span
          className="inline-flex max-w-full items-center gap-1.5 break-words rounded-full border px-2 py-0.5 text-[10.5px] [overflow-wrap:anywhere]"
          style={{
            color: state.color,
            borderColor: `${state.color}45`,
            backgroundColor: `${state.color}12`,
          }}
          role="status"
          aria-label={`${position.displayName}: ${statusText}`}
        >
          <Icon className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
          {statusText}
        </span>
      </div>
      {position.summary && (
        <div className="mt-3">
          <ExpandableText text={position.summary} t={t} />
        </div>
      )}
      <div className="mt-3">
        <EnumBadge
          prefix="results.structured.level"
          value={position.confidence}
          t={t}
          label={t("results.structured.positionConfidence")}
        />
      </div>
    </div>
  );
}

function providerPositionState(position) {
  return {
    supports: { icon: Check, color: "#10B981" },
    partially_supports: { icon: HelpCircle, color: "#FBBF24" },
    contradicts: { icon: AlertTriangle, color: "#F43F5E" },
    uncertain: { icon: HelpCircle, color: "#A78BFA" },
    not_mentioned: { icon: CircleMinus, color: "#F8FAFC" },
  }[position] || { icon: HelpCircle, color: "#94A3B8" };
}

function StructuredDisagreementCard({ disagreement, t }) {
  return (
    <article className="min-w-0 max-w-full rounded-xl border border-[#F59E0B]/15 bg-[#F59E0B]/[0.025] p-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <EnumBadge
          prefix="results.structured.disagreementType"
          value={disagreement.disagreementType}
          t={t}
        />
        <EnumBadge
          prefix="results.structured.verdictImpact"
          value={disagreement.impactOnVerdict}
          t={t}
          label={t("results.structured.verdictImpactLabel")}
        />
      </div>
      <p className="mt-3 break-words text-[14px] leading-relaxed text-white/90 [overflow-wrap:anywhere]">
        {disagreement.topic}
      </p>
      <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">
        {disagreement.positions.map((position) => (
          <div
            key={position.provider}
            className="min-w-0 max-w-full rounded-xl border border-white/[0.06] bg-black/10 p-3"
          >
            <ProviderChip provider={position.provider} />
            <p className="mt-2 break-words text-[12.5px] leading-relaxed text-white/65 [overflow-wrap:anywhere]">
              {position.position}
            </p>
          </div>
        ))}
      </div>
      <LabeledParagraph
        label={t("results.structured.refereeResolution")}
        text={disagreement.refereeResolution}
      />
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

function LabeledParagraph({ label, text, expandable = false, t }) {
  return (
    <div className="mt-3 border-t border-white/[0.06] pt-3">
      <div className="text-[10.5px] uppercase tracking-[0.14em] text-white/40">{label}</div>
      {expandable ? (
        <div className="mt-1">
          <ExpandableText text={text} t={t} />
        </div>
      ) : (
        <p className="mt-1 break-words text-[12.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">{text}</p>
      )}
    </div>
  );
}

function ExpandableText({ text, t, limit = 240 }) {
  const [expanded, setExpanded] = useState(false);
  const needsExpansion = String(text || "").length > limit;
  const visibleText = needsExpansion && !expanded
    ? `${String(text).slice(0, limit).trimEnd()}…`
    : text;
  return (
    <div className="min-w-0">
      <p className="break-words text-[12.5px] leading-relaxed text-white/60 [overflow-wrap:anywhere]">
        {visibleText}
      </p>
      {needsExpansion && (
        <button
          type="button"
          className="mt-2 min-h-11 rounded-lg px-2 text-[11.5px] font-medium text-[#00E5FF] transition-colors duration-200 hover:bg-[#00E5FF]/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF]"
          aria-label={expanded
            ? t("results.structured.showLess")
            : t("results.structured.showAll")}
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded
            ? t("results.structured.showLess")
            : t("results.structured.showAll")}
        </button>
      )}
    </div>
  );
}

function ConclusionSection({
  title,
  subtitle,
  icon: Icon,
  accent,
  testId,
  children,
  defaultOpen = false,
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  const headingId = useId();
  return (
    <section
      className="mt-8 min-w-0 max-w-full border-t border-white/[0.07] pt-5 sm:pt-7"
      data-testid={testId}
      data-open={open ? "true" : "false"}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        className="flex min-h-12 w-full min-w-0 items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors duration-200 hover:bg-white/[0.025] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120]"
        aria-label={title}
        aria-expanded={open}
        aria-controls={contentId}
        id={headingId}
        onClick={() => setOpen((value) => !value)}
        data-testid={testId ? `${testId}-toggle` : undefined}
      >
        {open
          ? <ChevronDown className="h-4 w-4 flex-shrink-0 text-white/45" aria-hidden="true" />
          : <ChevronRight className="h-4 w-4 flex-shrink-0 text-white/45" aria-hidden="true" />}
        <span
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border"
          style={{ color: accent, borderColor: `${accent}45`, backgroundColor: `${accent}12` }}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block break-words text-[15px] font-semibold text-white [overflow-wrap:anywhere]">
            {title}
          </span>
          {subtitle && (
            <span className="mt-1 block break-words text-[12.5px] leading-relaxed text-white/45 [overflow-wrap:anywhere]">
              {subtitle}
            </span>
          )}
        </span>
      </button>
      <div
        id={contentId}
        role="region"
        aria-labelledby={headingId}
        aria-hidden={!open}
        inert={!open}
        className={`grid transition-[grid-template-rows,opacity,margin] duration-200 ease-out ${
          open
            ? "mt-4 grid-rows-[1fr] opacity-100"
            : "mt-0 grid-rows-[0fr] opacity-0"
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="space-y-4">{children}</div>
        </div>
      </div>
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

function ProviderChip({ provider, displayName }) {
  return (
    <span className="inline-flex max-w-full break-words rounded-full border border-white/10 bg-white/[0.035] px-2 py-0.5 text-[10.5px] text-white/60 [overflow-wrap:anywhere]">
      {displayName || PROVIDER_LABELS[provider] || provider}
    </span>
  );
}

function LevelBadge({ label, value, t }) {
  return (
    <EnumBadge
      prefix="results.structured.level"
      value={value}
      label={label}
      t={t}
    />
  );
}

function EnumBadge({ prefix, value, t, label = "" }) {
  const translated = translateEnum(t, prefix, value);
  const content = label ? `${label}: ${translated}` : translated;
  return (
    <span
      className="inline-flex max-w-full break-words rounded-full border border-white/10 bg-white/[0.025] px-2.5 py-1 text-[10.5px] text-white/65 [overflow-wrap:anywhere]"
      aria-label={content}
    >
      {content}
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
