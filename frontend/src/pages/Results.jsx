import { useEffect, useMemo, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  MinusCircle,
  Sparkles,
  Trophy,
  ShieldCheck,
  MessagesSquare,
  Loader2,
  HelpCircle,
  Swords,
  BarChart3,
  Info,
  TrendingUp,
  TrendingDown,
  ChevronDown,
  ChevronRight,
  Star,
  ScatterChart,
  Lightbulb,
  Gauge,
  Recycle,
  Zap,
  RefreshCcw,
  Share2,
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { ClaimTraceability } from "@/components/ClaimTraceability";
import { ProviderLogo } from "@/components/ProviderLogo";
import { SafeAnswerText } from "@/components/SafeAnswerText";
import { StructuredConclusion } from "@/components/StructuredConclusion";
import { useQueryState } from "@/lib/QueryContext";
import { useI18n } from "@/lib/i18n";
import { localizeProviderError, translateEnum } from "@/lib/resultPresentation";
import { coveredClaimIdsForConclusion } from "@/lib/structuredConclusion";
import {
  PROVIDER_STATUS,
  failedProviderResponses,
  normalizeProviderResponses,
} from "@/lib/executionMode";
import {
  MODELS,
  LIVE_MODELS,
  MODEL_STATUS,
  MOCK_SCORES,
  MOCK_CONTRIBUTIONS,
  CHALLENGE_OUTCOMES,
  CONSENSUS_TIERS,
  EVIDENCE_METER,
  EVOLUTION_STEPS,
  WHY_CHOSE_ANSWER,
} from "@/lib/mockData";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const ANALYSIS_STEP_KEYS = [
  "results.analysisSteps.comparing",
  "results.analysisSteps.agreements",
  "results.analysisSteps.disagreements",
  "results.analysisSteps.consistency",
  "results.analysisSteps.uncertainty",
  "results.analysisSteps.arguments",
  "results.analysisSteps.preparing",
];
const CHALLENGE_STEP_KEYS = [
  "results.challengeSteps.evidence",
  "results.challengeSteps.logic",
  "results.challengeSteps.alternatives",
  "results.challengeSteps.contradictions",
  "results.challengeSteps.exceptions",
  "results.challengeSteps.recentInformation",
];

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: "easeOut" } },
};

export default function Results() {
  const navigate = useNavigate();
  const location = useLocation();
  const { query } = useQueryState();
  const { t } = useI18n();
  const prompt = query.prompt || t("results.defaultPrompt");

  const routeState = location.state || {};
  const mode = routeState.mode || "fresh"; // fresh | reused | updated
  const reuseTopic = routeState.topic;
  const reuseReason = routeState.reason;
  const reuseMatch = routeState.match || routeState.replacedMatch || null;
  const queryId = routeState.queryId || null;
  const answerLanguage = routeState.answerLanguage || "en";

  const [phase, setPhase] = useState(mode === "reused" ? "reveal" : "models");
  const [completedModels, setCompletedModels] = useState(mode === "reused" ? LIVE_MODELS.map((m) => m.id) : []);
  const [analysisStep, setAnalysisStep] = useState(mode === "reused" ? ANALYSIS_STEP_KEYS.length : 0);
  const [liveResponses, setLiveResponses] = useState(null); // [{id, label, text, is_mock, ...}]
  const [liveCount, setLiveCount] = useState(0);
  const [totalCost, setTotalCost] = useState(0);
  const [trustedConclusion, setTrustedConclusion] = useState("");
  const [structuredConclusion, setStructuredConclusion] = useState(null);
  const [conclusionSchemaVersion, setConclusionSchemaVersion] = useState(null);
  const [synthesisStatus, setSynthesisStatus] = useState("");
  const [synthesisError, setSynthesisError] = useState("");
  const [claims, setClaims] = useState([]);
  const [citations, setCitations] = useState([]);
  const [claimSchemaVersion, setClaimSchemaVersion] = useState(null);
  const [claimAnalysisStatus, setClaimAnalysisStatus] = useState("");
  const [claimAnalysisError, setClaimAnalysisError] = useState("");
  const [providerStatuses, setProviderStatuses] = useState([]);
  const [conclusionLoading, setConclusionLoading] = useState(mode !== "reused");
  const [executionMode, setExecutionMode] = useState("LIVE");
  const [retryNonce, setRetryNonce] = useState(0);
  const [sharePrompt, setSharePrompt] = useState(reuseMatch?.prompt || routeState.prompt || "");

  // Kick off the real comparison on mount (unless we're reusing a cached one)
  useEffect(() => {
    if (mode === "reused") return;
    let cancelled = false;
    setPhase("models");
    setAnalysisStep(0);
    setCompletedModels([]);
    setLiveResponses(null);
    setTrustedConclusion("");
    setStructuredConclusion(null);
    setConclusionSchemaVersion(null);
    setSynthesisStatus("");
    setSynthesisError("");
    setClaims([]);
    setCitations([]);
    setClaimSchemaVersion(null);
    setClaimAnalysisStatus("");
    setClaimAnalysisError("");
    setProviderStatuses([]);
    setConclusionLoading(true);

    if (!queryId) {
      const reason = t("results.errors.requestNotCreated");
      setLiveResponses(failedProviderResponses(LIVE_MODELS, reason));
      setCompletedModels(LIVE_MODELS.map((model) => model.id));
      setPhase("analysis");
      setConclusionLoading(false);
      return;
    }

    axios.post(`${API}/queries/${queryId}/compare`).then((r) => {
      if (cancelled) return;
      const responseExecutionMode = r.data?.execution_mode === "DEMO" ? "DEMO" : "LIVE";
      const responses = normalizeProviderResponses(r.data?.responses, responseExecutionMode);
      setExecutionMode(responseExecutionMode);
      setLiveResponses(responses);
      setLiveCount(responses.filter((response) => response.provider_status === PROVIDER_STATUS.LIVE).length);
      setTotalCost(r.data?.total_cost_usd || 0);
      setTrustedConclusion(r.data?.trusted_conclusion || "");
      setStructuredConclusion(r.data?.trusted_conclusion_structured || null);
      setConclusionSchemaVersion(r.data?.conclusion_schema_version || null);
      setSynthesisStatus(r.data?.synthesis_status || "");
      setSynthesisError(r.data?.synthesis_error || "");
      setClaims(Array.isArray(r.data?.claims) ? r.data.claims : []);
      setCitations(Array.isArray(r.data?.citations) ? r.data.citations : []);
      setClaimSchemaVersion(r.data?.claim_schema_version || null);
      setClaimAnalysisStatus(r.data?.claim_analysis_status || "");
      setClaimAnalysisError(r.data?.claim_analysis_error || "");
      setProviderStatuses(responses);
      if (r.data?.prompt) setSharePrompt(r.data.prompt);
      setCompletedModels(responses.map((response) => response.id));
      setPhase("analysis");
      setConclusionLoading(false);
    }).catch((e) => {
      console.warn("Compare failed", e);
      const reason = e?.response?.data?.detail || e?.message || t("results.errors.providerUnavailable");
      const responses = failedProviderResponses(LIVE_MODELS, reason);
      setExecutionMode("LIVE");
      setLiveResponses(responses);
      setLiveCount(0);
      setSynthesisStatus("FAILED");
      setSynthesisError(reason);
      setClaimAnalysisStatus("FAILED");
      setClaimAnalysisError(reason);
      setProviderStatuses(responses);
      setCompletedModels(responses.map((response) => response.id));
      setPhase("analysis");
      setConclusionLoading(false);
    });
    return () => { cancelled = true; };
  }, [queryId, mode, retryNonce, t]);

  // For reused mode, fetch the cached Trusted Conclusion in the current answer language.
  useEffect(() => {
    if (mode !== "reused") return;
    const targetId = reuseMatch?.id || queryId;
    if (!targetId) return;
    let cancelled = false;
    setConclusionLoading(true);
    axios.get(`${API}/conclusions/${targetId}`, { params: { lang: answerLanguage } })
      .then((r) => {
        if (cancelled) return;
        setTrustedConclusion(r.data?.trusted_conclusion || "");
        setStructuredConclusion(r.data?.trusted_conclusion_structured || null);
        setConclusionSchemaVersion(r.data?.conclusion_schema_version || null);
        setSynthesisStatus(r.data?.synthesis_status || "");
        setSynthesisError(r.data?.synthesis_error || "");
        setClaims(Array.isArray(r.data?.claims) ? r.data.claims : []);
        setCitations(Array.isArray(r.data?.citations) ? r.data.citations : []);
        setClaimSchemaVersion(r.data?.claim_schema_version || null);
        setClaimAnalysisStatus(r.data?.claim_analysis_status || "");
        setClaimAnalysisError(r.data?.claim_analysis_error || "");
        setProviderStatuses(Array.isArray(r.data?.provider_statuses) ? r.data.provider_statuses : []);
        setExecutionMode(r.data?.execution_mode === "DEMO" ? "DEMO" : "LIVE");
        setConclusionLoading(false);
      })
      .catch((e) => {
        console.warn("Fetch reused conclusion failed", e);
        setSynthesisStatus("FAILED");
        setSynthesisError(e?.response?.data?.detail || e?.message || t("results.errors.conclusionUnavailable"));
        setClaimAnalysisStatus("FAILED");
        setClaimAnalysisError(e?.response?.data?.detail || e?.message || t("results.errors.traceabilityUnavailable"));
        setConclusionLoading(false);
      });
    return () => { cancelled = true; };
  }, [mode, reuseMatch, queryId, answerLanguage, t]);

  // The pre-2.0 demo challenge remains dormant until it can consume
  // backend-generated structured data. It must never populate real results.
  const [challengePhase, setChallengePhase] = useState("idle");
  const [challengeStep, setChallengeStep] = useState(0);
  const [challengeOutcome, setChallengeOutcome] = useState(null);

  useEffect(() => {
    if (phase !== "analysis") return;
    if (analysisStep >= ANALYSIS_STEP_KEYS.length) {
      const t = setTimeout(() => setPhase("reveal"), 500);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setAnalysisStep((s) => s + 1), 550);
    return () => clearTimeout(t);
  }, [phase, analysisStep]);

  useEffect(() => {
    if (challengePhase !== "running") return;
    if (challengeStep >= CHALLENGE_STEP_KEYS.length) {
      const timer = setTimeout(() => {
        setChallengeOutcome(CHALLENGE_OUTCOMES.strengthened);
        setChallengePhase("done");
      }, 500);
      return () => clearTimeout(timer);
    }
    const timer = setTimeout(() => setChallengeStep((step) => step + 1), 620);
    return () => clearTimeout(timer);
  }, [challengePhase, challengeStep]);

  const currentConfidence = challengeOutcome
    ? challengeOutcome.newConfidence
    : MOCK_SCORES.confidence;
  return (
    <div className="relative min-h-screen max-w-full overflow-x-hidden bg-[#060A14] text-white" data-testid="results-page">
      <div className="pointer-events-none absolute inset-0 opacity-60 grid-pattern" />
      <NavBar variant="results" />

      <main className="relative mx-auto max-w-6xl px-5 md:px-8 pt-10 md:pt-14 pb-24">
        <button
          type="button"
          onClick={() => navigate("/")}
          data-testid="back-home-button"
          className="inline-flex min-h-11 items-center gap-1.5 rounded-lg text-[13px] text-white/50 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#060A14]"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> {t("results.backPrompt")}
        </button>

        <div className="mt-4 max-w-3xl">
          <div className="text-[11px] uppercase tracking-[0.2em] text-white/40 mb-2">{t("results.yourQuestion")}</div>
          <h1 className="break-words text-2xl font-semibold leading-snug tracking-tight [overflow-wrap:anywhere] md:text-3xl" data-testid="results-question">
            “{prompt}”
          </h1>
        </div>

        {/* Smart Reuse badge banner */}
        <ReuseBadgeBanner mode={mode} match={reuseMatch} topic={reuseTopic} reason={reuseReason} />

        <AnimatePresence>
          {phase !== "reveal" && (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
              className="mt-10"
              data-testid="loading-phase"
            >
              <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
                {LIVE_MODELS.map((m) => {
                  const done = completedModels.includes(m.id);
                  return (
                    <div
                      key={m.id}
                      data-testid={`load-${m.id}`}
                      className={
                        "relative min-w-0 max-w-full rounded-2xl border p-4 transition-colors sm:p-5 " +
                        (done ? "border-white/15 bg-white/[0.04]" : "border-white/[0.06] bg-[#0B1120]")
                      }
                    >
                      <span className="absolute left-0 top-5 bottom-5 w-[3px] rounded-r" style={{ backgroundColor: m.accent, boxShadow: `0 0 20px ${m.accent}80` }} />
                      <div className="flex min-w-0 flex-col items-start gap-3 pl-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="flex min-w-0 items-center gap-3">
                          <div className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium" style={{ backgroundColor: `${m.accent}18`, borderColor: `${m.accent}55`, color: m.accent }}>
                            <ProviderLogo
                              modelId={m.id}
                              provider={m.provider}
                              label={m.label}
                              initials={m.initials}
                            />
                          </div>
                          <div className="min-w-0">
                            <div className="break-words text-[14.5px] font-medium text-white [overflow-wrap:anywhere]">{m.label}</div>
                            <div className="break-words text-[11.5px] text-white/45 [overflow-wrap:anywhere]">{m.codename} · {m.provider}</div>
                          </div>
                        </div>
                        <div className="flex flex-shrink-0 items-center gap-2 text-[12px]">
                          {done ? (
                            <span className="inline-flex items-center gap-1.5 text-[#10B981]" data-testid={`load-${m.id}-complete`}>
                              <Check className="w-3.5 h-3.5" aria-hidden="true" /> {t("results.complete")}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-white/50" data-testid={`load-${m.id}-thinking`}>
                              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> {t("results.thinking")}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <AnimatePresence>
                {phase === "analysis" && (
                  <motion.div
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4 }}
                    className="mt-6 min-w-0 max-w-full rounded-2xl border border-[#00E5FF]/25 bg-[#00E5FF]/[0.04] p-4 sm:p-6"
                    data-testid="analysis-phase"
                    role="status"
                    aria-live="polite"
                  >
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-8 h-8 rounded-lg bg-[#00E5FF]/15 border border-[#00E5FF]/40 flex items-center justify-center">
                        <Sparkles className="w-4 h-4 text-[#00E5FF]" />
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">{t("results.consensusAnalysis")}</div>
                        <div className="text-[14px] text-white">{t("results.consensusAnalysisSub")}</div>
                      </div>
                    </div>
                    <ul className="space-y-2">
                      {ANALYSIS_STEP_KEYS.slice(0, analysisStep).map((key, i) => (
                        <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.35 }} className="flex items-center gap-2 text-[13.5px] text-white/80" data-testid={`analysis-step-${i}`}>
                          <Check className="w-3.5 h-3.5 flex-shrink-0 text-[#10B981]" aria-hidden="true" /> <span className="min-w-0 break-words">{t(key)}</span>
                        </motion.li>
                      ))}
                      {analysisStep < ANALYSIS_STEP_KEYS.length && (
                        <li className="flex items-center gap-2 text-[13.5px] text-white/60">
                          <Loader2 className="w-3.5 h-3.5 flex-shrink-0 animate-spin text-[#00E5FF]" aria-hidden="true" /> <span className="min-w-0 break-words">{t(ANALYSIS_STEP_KEYS[analysisStep])}</span>
                        </li>
                      )}
                    </ul>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          )}
        </AnimatePresence>

        {phase === "reveal" && (
          <RevealSection
            currentConfidence={currentConfidence}
            challengePhase={challengePhase}
            challengeStep={challengeStep}
            challengeOutcome={challengeOutcome}
            liveResponses={liveResponses}
            liveCount={liveCount}
            totalCost={totalCost}
            trustedConclusion={trustedConclusion}
            structuredConclusion={structuredConclusion}
            conclusionSchemaVersion={conclusionSchemaVersion}
            synthesisStatus={synthesisStatus}
            synthesisError={synthesisError}
            claims={claims}
            citations={citations}
            claimSchemaVersion={claimSchemaVersion}
            claimAnalysisStatus={claimAnalysisStatus}
            claimAnalysisError={claimAnalysisError}
            providerStatuses={providerStatuses}
            conclusionLoading={conclusionLoading}
            answerLanguage={answerLanguage}
            executionMode={executionMode}
            showProviderResults={mode !== "reused"}
            prompt={sharePrompt}
            onRetry={() => setRetryNonce((value) => value + 1)}
            onChallenge={() => {
              if (challengePhase === "idle") {
                setChallengeStep(0);
                setChallengeOutcome(null);
                setChallengePhase("running");
              }
            }}
            onSeeDebate={() => navigate("/debate", { state: { executionMode } })}
          />
        )}
      </main>
    </div>
  );
}

function RevealSection({ currentConfidence, challengePhase, challengeStep, challengeOutcome, onChallenge, onSeeDebate, onRetry, liveResponses, liveCount, totalCost, trustedConclusion, structuredConclusion, conclusionSchemaVersion, synthesisStatus, synthesisError, claims, citations, claimSchemaVersion, claimAnalysisStatus, claimAnalysisError, providerStatuses, conclusionLoading, answerLanguage, executionMode, showProviderResults, prompt }) {
  const modelById = useMemo(() => Object.fromEntries(MODELS.map((model) => [model.id, model])), []);
  const { t } = useI18n();
  const liveById = useMemo(() => {
    if (!liveResponses) return {};
    return Object.fromEntries(liveResponses.map((r) => [r.id, r]));
  }, [liveResponses]);
  const failedCount = (liveResponses || []).filter((response) => [
    PROVIDER_STATUS.FAILED,
    PROVIDER_STATUS.TIMEOUT,
  ].includes(response.provider_status)).length;
  const mockCount = (liveResponses || []).filter((response) => response.provider_status === PROVIDER_STATUS.MOCK).length;
  const isDemo = executionMode === "DEMO";
  const conclusionClaimIds = coveredClaimIdsForConclusion(structuredConclusion, claims);
  // Kept off until these legacy demo-only widgets are backed by the 2.0 API.
  // This prevents fixed mockData analytics from being presented as a verdict.
  const legacyDemoAnalyticsEnabled = false;

  return (
    <>
      {/* Live indicator strip */}
      {liveResponses && (
        <div className="mt-6 flex min-w-0 max-w-full flex-wrap items-center gap-2 text-[12px] text-white/60" data-testid="live-status" role="status">
          {executionMode === "DEMO" && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#FBBF24]/40 bg-[#FBBF24]/[0.08] px-2.5 py-0.5 text-[#FBBF24]" data-testid="execution-mode-demo">
              {t("results.status.demo")}
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[#10B981]/40 bg-[#10B981]/[0.08] px-2.5 py-0.5 text-[#10B981]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#10B981]" aria-hidden="true" />
            {t("results.status.liveCount", { n: liveCount })}
          </span>
          {mockCount > 0 && executionMode === "DEMO" && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#FBBF24]/40 bg-[#FBBF24]/[0.08] px-2.5 py-0.5 text-[#FBBF24]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FBBF24]" aria-hidden="true" />
              {t("results.status.mockCount", { n: mockCount })}
            </span>
          )}
          {failedCount > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#F43F5E]/50 bg-[#F43F5E]/[0.08] px-2.5 py-0.5 text-[#F43F5E]" data-testid="fallback-summary">
              <span className="w-1.5 h-1.5 rounded-full bg-[#F43F5E]" aria-hidden="true" />
              {t("results.status.failedCount", { n: failedCount })}
            </span>
          )}
          {typeof totalCost === "number" && totalCost > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-0.5 text-white/70 font-mono" data-testid="total-cost">
              ~${totalCost.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}
            </span>
          )}
          <span className="min-w-0 break-words text-white/40 [overflow-wrap:anywhere]">{t("results.roadmapProviders")}</span>
        </div>
      )}

      {/* Model cards — now expandable */}
      {showProviderResults && <motion.div
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } } }}
        className="mt-6 grid min-w-0 grid-cols-1 gap-5 md:grid-cols-2"
        data-testid="models-grid"
      >
        {MODELS.map((m) => {
          if (m.status !== MODEL_STATUS.LIVE) {
            return <ComingSoonModelCard key={m.id} model={m} />;
          }
          const live = liveById[m.id] || {
            id: m.id,
            provider_status: m.id === "model-e"
              ? PROVIDER_STATUS.DISABLED
              : PROVIDER_STATUS.FAILED,
            provider_error: t("results.errors.providerResultUnavailable"),
            text: "",
          };
          return (
            <ExpandableModelCard
              key={m.id}
              model={m}
              codename={live?.codename || m.codename}
              response={live.text}
              details={null}
              contribution={null}
              latencyMs={live?.provider_latency ?? live?.latency_ms ?? 0}
              tokens={live?.total_tokens ?? 0}
              inputTokens={live?.input_tokens}
              outputTokens={live?.output_tokens}
              costUsd={live?.cost_usd}
              modelUsed={live?.model_used}
              providerStatus={live.provider_status}
              executionMode={executionMode}
              error={live.provider_error || live.error}
              onRetry={onRetry}
            />
          );
        })}
      </motion.div>}

      {/* Trusted Conclusion */}
      <motion.section
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: "easeOut", delay: 0.1 }}
        className="relative mt-12 min-w-0 max-w-full overflow-hidden rounded-3xl border border-[#0066FF]/40"
        data-testid="trusted-conclusion-card"
      >
        <div className="absolute inset-0 super-glow" />
        <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-[#00E5FF]/60 to-transparent" />
        <div className="relative p-4 sm:p-6 md:p-10">
          <div className="mb-5 flex min-w-0 items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 flex items-center justify-center flex-shrink-0">
              <Sparkles className="w-4 h-4 text-[#00E5FF]" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">{t("results.refereeVerdict")}</div>
              <h2 className="text-2xl md:text-3xl font-semibold tracking-tight text-white">{t("results.trustedConclusion")}</h2>
            </div>
            <button
              type="button"
              onClick={async () => {
                const text = `AI Referee\n\n${prompt ? `${t("results.shareQuestionLabel")}: ${prompt}\n\n` : ""}${t("results.shareVerdictLabel")}: ${trustedConclusion || ""}\n\n${typeof window !== "undefined" ? window.location.href : ""}`.trim();
                const shareData = { title: "AI Referee", text, url: typeof window !== "undefined" ? window.location.href : "" };
                try {
                  if (typeof navigator !== "undefined" && navigator.share) {
                    await navigator.share(shareData);
                    toast.success(t("results.shareShared"));
                  } else if (typeof navigator !== "undefined" && navigator.clipboard) {
                    await navigator.clipboard.writeText(text);
                    toast.success(t("results.shareCopied"));
                  } else {
                    toast.error(t("results.shareUnavailable"));
                  }
                } catch (err) {
                  if (err && err.name === "AbortError") return; // user cancelled
                  try {
                    if (typeof navigator !== "undefined" && navigator.clipboard) {
                      await navigator.clipboard.writeText(text);
                      toast.success(t("results.shareCopied"));
                      return;
                    }
                  } catch { /* ignore */ }
                  toast.error(t("results.shareUnavailable"));
                }
              }}
              disabled={conclusionLoading || !trustedConclusion}
              data-testid="share-verdict-button"
              aria-label={t("results.shareVerdict")}
              className="inline-flex min-h-11 flex-shrink-0 items-center gap-1.5 rounded-full border border-[#00E5FF]/40 bg-[#00E5FF]/[0.08] px-3 py-1.5 text-[12px] text-[#00E5FF] transition-colors hover:bg-[#00E5FF]/[0.14] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120] disabled:pointer-events-none disabled:opacity-40"
            >
              <Share2 className="w-3.5 h-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">{t("results.shareVerdict")}</span>
            </button>
          </div>

          <div
            data-testid="trusted-conclusion-body"
            data-answer-language={answerLanguage}
            data-conclusion-schema={conclusionSchemaVersion || (trustedConclusion ? "legacy" : "none")}
          >
            {conclusionLoading ? (
              <span className="inline-flex items-center gap-2 text-white/50 text-[14px]" data-testid="trusted-conclusion-loading">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF] animate-pulse" />
                {t("results.synthesizing")}
              </span>
            ) : (
              <StructuredConclusion
                structured={structuredConclusion}
                legacyText={trustedConclusion}
                synthesisStatus={synthesisStatus}
                synthesisError={synthesisError}
                claims={claims}
                t={t}
              />
            )}
            {!conclusionLoading && (
              <div data-claim-schema={claimSchemaVersion || "none"}>
                <ClaimTraceability
                  claims={claims}
                  citations={citations}
                  claimAnalysisStatus={claimAnalysisStatus}
                  claimAnalysisError={claimAnalysisError}
                  providerStatuses={providerStatuses}
                  executionMode={executionMode}
                  excludeClaimIds={conclusionClaimIds}
                  hideSources={Boolean(
                    structuredConclusion?.schema_version === "2.1"
                    && structuredConclusion?.source_summary?.length
                  )}
                  t={t}
                />
              </div>
            )}
          </div>

          {legacyDemoAnalyticsEnabled && isDemo && <AnimatePresence>
            {challengePhase !== "idle" && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="mt-8"
                data-testid="challenge-block"
              >
                {challengePhase === "running" ? (
                  <div className="rounded-2xl border border-[#F59E0B]/30 bg-[#F59E0B]/[0.04] p-5">
                    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-[#F59E0B] mb-3">
                      <Swords className="w-3.5 h-3.5" aria-hidden="true" /> {t("results.challengeProgress")}
                    </div>
                    <ul className="space-y-2">
                      {CHALLENGE_STEP_KEYS.slice(0, challengeStep).map((key, i) => (
                        <li key={i} className="flex items-center gap-2 text-[13.5px] text-white/80" data-testid={`challenge-step-${i}`}>
                          <Check className="w-3.5 h-3.5 text-[#10B981]" aria-hidden="true" /> {t(key)}
                        </li>
                      ))}
                      {challengeStep < CHALLENGE_STEP_KEYS.length && (
                        <li className="flex items-center gap-2 text-[13.5px] text-white/60">
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-[#F59E0B]" aria-hidden="true" /> {t(CHALLENGE_STEP_KEYS[challengeStep])}
                        </li>
                      )}
                    </ul>
                  </div>
                ) : challengeOutcome ? (
                  <div
                    className={
                      "rounded-2xl border p-5 " +
                      (challengeOutcome.result === "strengthened"
                        ? "border-[#10B981]/30 bg-[#10B981]/[0.05]"
                        : "border-[#F43F5E]/30 bg-[#F43F5E]/[0.05]")
                    }
                    data-testid="challenge-outcome"
                  >
                    <div className="flex items-center justify-between mb-3 gap-4 flex-wrap">
                      <div className="flex items-center gap-2 text-[13px] font-medium">
                        {challengeOutcome.result === "strengthened" ? (
                          <TrendingUp className="w-4 h-4 text-[#10B981]" />
                        ) : (
                          <TrendingDown className="w-4 h-4 text-[#F43F5E]" />
                        )}
                        <span className="text-white">{challengeOutcome.headline}</span>
                      </div>
                      <div className="flex items-center gap-2 font-mono text-[12px]">
                        <span className="text-white/50">{MOCK_SCORES.confidence}%</span>
                        <ArrowRight className="w-3.5 h-3.5 text-white/40" />
                        <span className={challengeOutcome.result === "strengthened" ? "text-[#10B981]" : "text-[#F43F5E]"}>
                          {challengeOutcome.newConfidence}%
                        </span>
                      </div>
                    </div>
                    <p className="text-[13.5px] text-white/70 leading-relaxed">{challengeOutcome.body}</p>
                    <ul className="mt-3 space-y-1.5">
                      {challengeOutcome.findings.map((f, i) => (
                        <li key={i} className="flex gap-2 text-[13px] text-white/65">
                          <span className="mt-2 w-1.5 h-1.5 rounded-full bg-white/40 flex-shrink-0" />
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </motion.div>
            )}
          </AnimatePresence>}

          <div className="mt-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-6 border-t border-white/[0.08]">
            <div className="flex flex-wrap items-center gap-3 text-[12px] text-white/50">
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF]" />
                {isDemo
                  ? t("results.synthesizedFromMock", { n: mockCount })
                  : t("results.synthesizedFromLive", { n: liveCount })}
              </span>
              {legacyDemoAnalyticsEnabled && isDemo && <>
                <span>·</span>
                <span>{t("results.confidence")} {currentConfidence}%</span>
                <span>·</span>
                <span>{t("results.consensus")} {MOCK_SCORES.consensus}%</span>
              </>}
            </div>
            {legacyDemoAnalyticsEnabled && isDemo && <button
              type="button"
              onClick={onChallenge}
              disabled={challengePhase === "running"}
              data-testid="challenge-conclusion-button"
              className="group inline-flex min-h-11 items-center gap-2 rounded-full border border-[#F59E0B]/40 bg-[#F59E0B]/[0.08] px-5 py-2.5 text-[13px] font-medium text-[#F59E0B] transition-colors hover:bg-[#F59E0B]/[0.14] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F59E0B] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120] disabled:opacity-70"
            >
              <Swords className="w-4 h-4" />
              {challengePhase === "idle" ? t("results.challengeConclusion") : challengePhase === "running" ? t("results.challenging") : t("results.challengeAgain")}
            </button>}
          </div>
        </div>
      </motion.section>

      {legacyDemoAnalyticsEnabled && isDemo && <>
      {/* Why this conclusion? — demo-only analytical cards */}
      <SectionHeader
        className="mt-16"
        eyebrow={t("results.transparencyEyebrow")}
        title={t("results.whyConclusion")}
        body={t("results.whyBody")}
      />
      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="why-conclusion-grid">
        <FullConsensusCard tier={CONSENSUS_TIERS.full} />
        <PartialConsensusCard tier={CONSENSUS_TIERS.partial} modelById={modelById} />
        <DisagreementsCard tier={CONSENSUS_TIERS.disagreements} modelById={modelById} />
        <UniqueInsightsCard tier={CONSENSUS_TIERS.unique} modelById={modelById} />
      </div>

      {/* Evidence Meter */}
      <EvidenceMeterSection />

      {/* Consensus Evolution timeline */}
      <ConsensusEvolutionTimeline />

      {/* Why did AI Referee choose this answer? */}
      <SectionHeader
        className="mt-16"
        eyebrow={t("results.rationaleEyebrow")}
        title={t("results.whyChoseAnswer")}
        body={t("results.rationaleBody")}
      />
      <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-4" data-testid="why-referee-chose">
        {WHY_CHOSE_ANSWER.map((_, i) => (
          <RationaleCard
            key={i}
            index={i + 1}
            title={t(`results.rationaleItems.${i}.title`)}
            body={t(`results.rationaleItems.${i}.body`)}
            testId={`rationale-${i}`}
          />
        ))}
      </div>

      {/* View Full Debate CTA */}
      <div className="mt-10 flex justify-center">
        <button
          type="button"
          onClick={onSeeDebate}
          data-testid="view-full-debate-button"
          className="group inline-flex min-h-11 items-center gap-2 rounded-full bg-white px-6 py-3 text-[14px] font-medium text-[#060A14] transition-colors hover:bg-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#060A14]"
          style={{ boxShadow: "0 20px 50px -18px rgba(0,229,255,0.6)" }}
        >
          <MessagesSquare className="w-4 h-4" />
          {t("results.viewDebate")}
          <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
        </button>
      </div>

      {/* Contribution chart */}
      <motion.section
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.6 }}
        className="mt-16 rounded-2xl border border-white/[0.08] bg-[#0B1120] p-6 md:p-8"
        data-testid="contribution-card"
      >
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-2">
          <BarChart3 className="w-3.5 h-3.5" /> {t("results.modelContribution")}
        </div>
        <h3 className="text-xl font-semibold tracking-tight text-white">{t("results.contributionTitle")}</h3>
        <div className="mt-6 space-y-4">
          {MOCK_CONTRIBUTIONS.map((c) => {
            const m = modelById[c.modelId];
            return (
              <div key={c.modelId} data-testid={`contribution-${c.modelId}`}>
                <div className="flex items-center justify-between mb-1.5 text-[13px]">
                  <div className="flex items-center gap-2 text-white/85">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: m.accent }} />
                    <span className="font-medium">{m.label}</span>
                    <span className="text-white/40">· {m.codename}</span>
                  </div>
                  <span className="font-mono text-white/70">{c.pct}%</span>
                </div>
                <div className="h-2 rounded-full bg-white/[0.05] overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    whileInView={{ width: `${c.pct}%` }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.9, ease: "easeOut" }}
                    className="h-full rounded-full"
                    style={{ backgroundColor: m.accent, boxShadow: `0 0 18px ${m.accent}70` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </motion.section>
      </>}

      {/* Transparency */}
      <div
        className="mt-8 flex min-w-0 max-w-full items-start gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4 sm:p-5"
        data-testid="transparency-note"
      >
        <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-white/50" aria-hidden="true" />
        <p className="min-w-0 break-words text-[13px] leading-relaxed text-white/60 [overflow-wrap:anywhere]">{t("results.transparencyNote")}</p>
      </div>
    </>
  );
}

/* -------------------- Sub-components -------------------- */

function ReuseBadgeBanner({ mode, match, topic, reason }) {
  const { t } = useI18n();
  if (!mode || mode === "fresh") {
    return (
      <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-[#0066FF]/40 bg-[#0066FF]/[0.08] px-3.5 py-1.5 text-[12px] text-[#00E5FF]" data-testid="badge-fresh">
        <Sparkles className="w-3.5 h-3.5" />
        {t("badge.fresh")}
        {reason && <span className="text-white/50 ml-1 hidden sm:inline"> · {reason}</span>}
      </div>
    );
  }

  const isReused = mode === "reused";
  const accent = isReused ? "#00E5FF" : "#10B981";
  const label = isReused ? t("badge.reused") : t("badge.updated");
  const Icon = isReused ? Recycle : RefreshCcw;

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="mt-6 rounded-2xl border p-4 md:p-5 flex items-start gap-4 flex-wrap"
      style={{
        borderColor: `${accent}55`,
        background: `linear-gradient(180deg, ${accent}12, rgba(11,17,32,0.7) 70%)`,
      }}
      data-testid={isReused ? "badge-reused" : "badge-updated"}
    >
      <div
        className="w-10 h-10 rounded-xl border flex-shrink-0 flex items-center justify-center"
        style={{ backgroundColor: `${accent}20`, borderColor: `${accent}55` }}
      >
        <Icon className="w-4 h-4" style={{ color: accent }} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="text-[13.5px] font-medium text-white">{label}</div>
          {match && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] font-mono text-white/70">
              {match.similarity}{t("results.matchAgeStrip", { days: match.age_days })}
            </span>
          )}
          {topic && (
            <span className="max-w-full break-words text-[11px] uppercase tracking-[0.2em] text-white/40 font-mono [overflow-wrap:anywhere]" data-testid="reuse-topic-badge">{translateEnum(t, "results.topic", topic)}</span>
          )}
        </div>
        <div className="mt-1 text-[12.5px] text-white/60 leading-relaxed">
          {isReused ? t("results.reusedExplainer") : t("results.updatedExplainer")}
          {match && (
            <span className="break-words text-white/40 [overflow-wrap:anywhere]"> · {t("results.previousQuestion")}: <span className="italic text-white/60">“{match.prompt}”</span></span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function ComingSoonModelCard({ model: m }) {
  const { t } = useI18n();
  const isPremium = m.status === MODEL_STATUS.PREMIUM_COMING_SOON;
  const accentBadge = isPremium
    ? "text-[#FBBF24] border-[#FBBF24]/40 bg-[#FBBF24]/[0.08]"
    : "text-white/60 border-white/15 bg-white/[0.04]";
  const label = isPremium ? t("providers.premiumSoon") : t("providers.comingSoon");
  return (
    <motion.article
      variants={item}
      data-testid={`card-${m.id}`}
      data-status={m.status}
      className="relative min-w-0 max-w-full rounded-2xl border border-dashed border-white/[0.12] bg-[#0B1120]/60 opacity-90"
      style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)" }}
    >
      <span className={`absolute left-0 top-6 bottom-6 w-[3px] rounded-r ${m.accentClass || ""}`} style={{ backgroundColor: `${m.accent}55` }} />
      <div className="flex min-w-0 items-start justify-between gap-3 p-4 pl-7 sm:p-6 sm:pl-9">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium flex-shrink-0"
            style={{ backgroundColor: `${m.accent}12`, borderColor: `${m.accent}40`, color: m.accent }}
          >
            <ProviderLogo
              modelId={m.id}
              provider={m.provider}
              label={m.label}
              initials={m.initials}
            />
          </div>
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <div className="min-w-0 break-words text-[14.5px] font-medium text-white/85 [overflow-wrap:anywhere]">{m.label}</div>
              {isPremium && (
                <span className="text-[11px] text-[#FBBF24]" aria-hidden data-testid={`card-${m.id}-premium-star`}>★</span>
              )}
              <span
                data-testid={`card-${m.id}-status`}
                className={"inline-flex max-w-full flex-shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-[0.14em] uppercase " + accentBadge}
              >
                {label}
              </span>
            </div>
            <div className="break-words text-[11.5px] text-white/40 [overflow-wrap:anywhere]">{m.codename} · {m.provider}</div>
          </div>
        </div>
      </div>
      <div className="break-words px-4 pb-5 pl-7 text-[13.5px] italic leading-[1.65] text-white/50 [overflow-wrap:anywhere] sm:px-6 sm:pb-6 sm:pl-9" data-testid={`response-${m.id}`}>
        {isPremium
          ? t("results.providers.premiumDescription", { model: m.provider })
          : t("results.providers.roadmapDescription", { model: m.provider })}
      </div>
    </motion.article>
  );
}

function ExpandableModelCard({ model: m, response, details, contribution, codename, latencyMs, tokens, providerStatus, executionMode, error, inputTokens, outputTokens, costUsd, modelUsed, onRetry }) {
  const [open, setOpen] = useState(false);
  const { t, lang } = useI18n();
  const displayCodename = modelUsed || codename || m.codename;
  const status = providerStatus || PROVIDER_STATUS.FAILED;
  const localizedError = localizeProviderError(t, lang, error, status);
  const showLive = status === PROVIDER_STATUS.LIVE;
  const isFailed = status === PROVIDER_STATUS.FAILED;
  const isTimeout = status === PROVIDER_STATUS.TIMEOUT;
  const isDisabled = status === PROVIDER_STATUS.DISABLED;
  const isUnavailable = isFailed || isTimeout || isDisabled;
  const showMock = status === PROVIDER_STATUS.MOCK && executionMode === "DEMO";

  let badge;
  if (showLive) {
    badge = (
      <span className="flex-shrink-0 rounded-full border border-[#10B981]/40 bg-[#10B981]/[0.1] px-1.5 py-0.5 text-[9.5px] font-mono tracking-wider text-[#10B981]" data-testid={`card-${m.id}-live`}>{t("results.status.live")}</span>
    );
  } else if (isFailed) {
    badge = (
      <span className="flex-shrink-0 rounded-full border border-[#F43F5E]/50 bg-[#F43F5E]/[0.1] px-1.5 py-0.5 text-[9.5px] font-mono tracking-wider text-[#F43F5E]" title={localizedError} data-testid={`card-${m.id}-failed`}>{t("results.status.failed")}</span>
    );
  } else if (isTimeout) {
    badge = (
      <span className="flex-shrink-0 rounded-full border border-[#F59E0B]/50 bg-[#F59E0B]/[0.1] px-1.5 py-0.5 text-[9.5px] font-mono tracking-wider text-[#F59E0B]" title={localizedError} data-testid={`card-${m.id}-timeout`}>{t("results.status.timeout")}</span>
    );
  } else if (isDisabled) {
    badge = (
      <span className="flex-shrink-0 rounded-full border border-white/20 bg-white/[0.05] px-1.5 py-0.5 text-[9.5px] font-mono tracking-wider text-white/50" title={localizedError} data-testid={`card-${m.id}-disabled`}>{t("results.status.disabled")}</span>
    );
  } else {
    badge = (
      <span className="flex-shrink-0 rounded-full border border-[#FBBF24]/40 bg-[#FBBF24]/[0.1] px-1.5 py-0.5 text-[9.5px] font-mono tracking-wider text-[#FBBF24]" data-testid={`card-${m.id}-mocked`}>{showMock ? t("results.status.mock") : t("results.status.failed")}</span>
    );
  }

  const formatCost = (c) => {
    if (!c || c === 0) return "$0";
    if (c < 0.0001) return "<$0.0001";
    return `$${c.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
  };

  return (
    <motion.article
      variants={item}
      data-testid={`card-${m.id}`}
      className="group relative min-w-0 max-w-full rounded-2xl border border-white/[0.08] bg-[#0B1120] transition-colors hover:border-white/20"
      style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)" }}
    >
      <span className={`absolute left-0 top-6 bottom-6 w-[3px] rounded-r ${m.accentClass}`} />
      <header className="flex min-w-0 flex-col items-start gap-3 p-4 pl-7 sm:flex-row sm:justify-between sm:p-6 sm:pl-9">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium flex-shrink-0" style={{ backgroundColor: `${m.accent}18`, borderColor: `${m.accent}55`, color: m.accent }}>
            <ProviderLogo
              modelId={m.id}
              provider={m.provider}
              label={m.label}
              initials={m.initials}
            />
          </div>
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <div className="min-w-0 break-words text-[14.5px] font-medium text-white [overflow-wrap:anywhere]">{m.label}</div>
              {badge}
            </div>
            <div className="break-words text-[11.5px] text-white/45 [overflow-wrap:anywhere]" data-testid={`card-${m.id}-model`}>{displayCodename} · {m.provider}</div>
          </div>
        </div>
        {details && <div className="flex flex-shrink-0 items-center gap-3 text-[11px] font-mono text-white/40">
          <span data-testid={`card-${m.id}-confidence`}>{t("results.stats.confidenceShort")} {details.confidence}%</span>
          <span>·</span>
          <span data-testid={`card-${m.id}-contribution`}>{t("results.stats.contributionShort")} {contribution}%</span>
        </div>}
      </header>
      {isUnavailable ? (
        <div className="min-w-0 max-w-full px-4 pl-7 text-[14px] text-white/70 sm:px-6 sm:pl-9" data-testid={`response-${m.id}`} role="alert">
          <div className="font-medium text-[#F43F5E]">
            {isTimeout
              ? t("results.errors.providerTimeout")
              : isDisabled
                ? t("results.errors.providerDisabled")
                : t("results.errors.providerUnavailable")}
          </div>
          <div className="mt-2 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]" data-testid={`card-${m.id}-error`}>
            {localizedError}
          </div>
          {!isDisabled && <button
            type="button"
            onClick={onRetry}
            className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-full border border-[#F43F5E]/40 bg-[#F43F5E]/[0.08] px-4 py-2 text-[12px] font-medium text-[#F43F5E] transition-colors hover:bg-[#F43F5E]/[0.14] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F43F5E] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120]"
            data-testid={`retry-${m.id}`}
          >
            <RefreshCcw className="w-3.5 h-3.5" aria-hidden="true" /> {t("results.retry")}
          </button>}
        </div>
      ) : (
        <SafeAnswerText
          text={response}
          className="px-4 pl-7 text-[14.5px] leading-[1.65] text-white/75 sm:px-6 sm:pl-9"
          testId={`response-${m.id}`}
        />
      )}
      <div className="mt-3 flex min-w-0 max-w-full flex-wrap gap-x-3 gap-y-1 px-4 pl-7 text-[11px] font-mono text-white/40 sm:px-6 sm:pl-9" data-testid={`card-${m.id}-stats`}>
        <span>{latencyMs ?? m.latencyMs}ms</span>
        <span>·</span>
        <span>{t("results.stats.input")} {inputTokens ?? 0}</span>
        <span>·</span>
        <span>{t("results.stats.output")} {outputTokens ?? 0}</span>
        <span>·</span>
        <span title={t("results.stats.estimatedCost")}>~{formatCost(costUsd || 0)}</span>
      </div>
      {details && !isUnavailable && <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid={`expand-${m.id}`}
        aria-expanded={open}
        aria-controls={`details-${m.id}`}
        className="mt-5 flex min-h-11 w-full items-center justify-between rounded-b-2xl border-t border-white/[0.06] px-4 py-3 text-[12.5px] text-white/60 transition-colors hover:bg-white/[0.02] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#00E5FF] sm:px-6"
      >
        <span className="flex items-center gap-2">
          <ScatterChart className="w-3.5 h-3.5" />
          {open ? t("results.hideBreakdown") : t("results.showBreakdown")}
        </span>
        <ChevronDown className={"w-4 h-4 transition-transform " + (open ? "rotate-180" : "")} />
      </button>}
      <AnimatePresence initial={false}>
        {open && details && !isUnavailable && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
            className="overflow-hidden"
            data-testid={`details-${m.id}`}
            id={`details-${m.id}`}
          >
            <div className="space-y-5 px-4 pb-5 pl-7 sm:px-6 sm:pb-6 sm:pl-9">
              <ModelDetailBlock title={t("results.mainArguments")} items={details.mainArguments} accent={m.accent} />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <ModelDetailBlock title={t("results.strengths")} items={details.strengths} accent="#10B981" />
                <ModelDetailBlock title={t("results.weaknesses")} items={details.weaknesses} accent="#F43F5E" />
              </div>
              <div className="pt-2">
                <div className="flex items-center justify-between mb-1.5 text-[12px] text-white/60">
                  <span className="uppercase tracking-[0.2em] text-[10.5px]">{t("results.confidence")}</span>
                  <span className="font-mono text-white/85">{details.confidence}%</span>
                </div>
                <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${details.confidence}%`, backgroundColor: m.accent, boxShadow: `0 0 14px ${m.accent}80` }} />
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
}

function ModelDetailBlock({ title, items, accent }) {
  return (
    <div className="min-w-0 max-w-full">
      <div className="mb-2 break-words text-[10.5px] uppercase tracking-[0.22em] text-white/45 [overflow-wrap:anywhere]">{title}</div>
      <ul className="space-y-1.5">
        {items.map((t, i) => (
          <li key={i} className="flex min-w-0 gap-2 text-[13px] leading-relaxed text-white/75">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: accent }} />
            <span className="min-w-0 break-words [overflow-wrap:anywhere]">{t}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TierCard({ accent, label, badge, whyLabel, why, testId, children }) {
  return (
    <div
      className="relative min-w-0 max-w-full rounded-2xl border p-4 backdrop-blur-xl sm:p-6"
      style={{
        borderColor: `${accent}40`,
        background: `linear-gradient(180deg, ${accent}0d, rgba(11,17,32,0.75) 60%)`,
        boxShadow: `inset 0 1px 0 ${accent}22`,
      }}
      data-testid={testId}
    >
      <div className="flex items-start justify-between mb-4 gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${accent}20`, border: `1px solid ${accent}55` }}>
            {badge}
          </div>
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-[0.22em]" style={{ color: accent }}>{whyLabel}</div>
            <div className="break-words text-[16px] font-semibold tracking-tight text-white [overflow-wrap:anywhere]">{label}</div>
          </div>
        </div>
      </div>
      {why && (
        <p className="mb-4 break-words text-[12.5px] leading-relaxed text-white/50 [overflow-wrap:anywhere]">{why}</p>
      )}
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function FullConsensusCard({ tier }) {
  const { t } = useI18n();
  return (
    <TierCard
      accent={tier.accent}
      label={t("results.tier.full")}
      badge={<Check className="w-4 h-4" style={{ color: tier.accent }} />}
      whyLabel={t("results.tier.fullWhy", { pct: tier.percent })}
      why={tier.why}
      testId="tier-full-consensus"
    >
      {tier.items.map((it, i) => (
        <div key={i} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3" data-testid={`full-item-${i}`}>
          <div className="break-words text-[13.5px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">{it.text}</div>
          <div className="mt-1.5 break-words text-[11.5px] italic text-white/40 [overflow-wrap:anywhere]">{it.why}</div>
        </div>
      ))}
    </TierCard>
  );
}

function PartialConsensusCard({ tier, modelById }) {
  const { t } = useI18n();
  return (
    <TierCard
      accent={tier.accent}
      label={t("results.tier.partial")}
      badge={<Star className="w-4 h-4" style={{ color: tier.accent }} />}
      whyLabel={t("results.tier.partialWhy")}
      why={tier.why}
      testId="tier-partial-consensus"
    >
      {tier.items.map((it, i) => (
        <div key={i} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3" data-testid={`partial-item-${i}`}>
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="min-w-0 flex-1 break-words text-[13.5px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">{it.text}</div>
            <span className="text-[10.5px] font-mono px-1.5 py-0.5 rounded-md border border-[#00E5FF]/40 text-[#00E5FF] flex-shrink-0">{it.confidence}%</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {it.agreedBy.map((mid) => (
              <ModelChip key={mid} m={modelById[mid]} tone="agree" />
            ))}
            {it.disagreedBy.map((mid) => (
              <ModelChip key={mid} m={modelById[mid]} tone="disagree" />
            ))}
          </div>
          <div className="break-words text-[11.5px] italic text-white/45 [overflow-wrap:anywhere]">{it.why}</div>
        </div>
      ))}
    </TierCard>
  );
}

function DisagreementsCard({ tier, modelById }) {
  const { t } = useI18n();
  return (
    <TierCard
      accent={tier.accent}
      label={t("results.tier.disagreements")}
      badge={<MinusCircle className="w-4 h-4" style={{ color: tier.accent }} />}
      whyLabel={t("results.tier.disagreementsWhy")}
      why={tier.why}
      testId="tier-disagreements"
    >
      {tier.items.map((it, i) => (
        <div key={i} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3" data-testid={`disagreement-item-${i}`}>
          <div className="text-[12px] uppercase tracking-[0.18em] text-white/45 mb-2">{it.topic}</div>
          <div className="space-y-2">
            {it.positions.map((p, pi) => {
              const m = modelById[p.modelId];
              return (
                <div key={pi} className="flex gap-2.5">
                  <div className="w-7 h-7 rounded-md border flex-shrink-0 flex items-center justify-center text-[10.5px] font-medium mt-0.5" style={{ backgroundColor: `${m.accent}18`, borderColor: `${m.accent}55`, color: m.accent }}>
                    <ProviderLogo
                      modelId={m.id}
                      provider={m.provider}
                      label={m.label}
                      initials={m.initials}
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="break-words text-[12px] font-medium text-white [overflow-wrap:anywhere]">{m.label}</div>
                    <div className="mt-0.5 break-words text-[13px] leading-relaxed text-white/75 [overflow-wrap:anywhere]">“{p.stance}”</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </TierCard>
  );
}

function UniqueInsightsCard({ tier, modelById }) {
  const { t } = useI18n();
  return (
    <TierCard
      accent={tier.accent}
      label={t("results.tier.unique")}
      badge={<Lightbulb className="w-4 h-4" style={{ color: tier.accent }} />}
      whyLabel={t("results.tier.uniqueWhy")}
      why={tier.why}
      testId="tier-unique-insights"
    >
      {tier.items.map((it, i) => {
        const m = modelById[it.modelId];
        return (
          <div key={i} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3" data-testid={`unique-item-${i}`}>
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex min-w-0 flex-wrap items-center gap-2 text-[12px] text-white/70">
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: m.accent }} />
                <span className="break-words font-medium text-white [overflow-wrap:anywhere]">{m.label}</span>
                <span className="text-white/40">{t("results.only")}</span>
              </div>
              <span className="text-[10.5px] font-mono px-1.5 py-0.5 rounded-md border border-[#A78BFA]/40 text-[#A78BFA]">{it.label}</span>
            </div>
            <div className="break-words text-[13.5px] leading-relaxed text-white/85 [overflow-wrap:anywhere]">{it.text}</div>
            <div className="mt-1.5 break-words text-[11.5px] italic text-white/45 [overflow-wrap:anywhere]">{t("results.whyStillValuable")}: {it.value}</div>
          </div>
        );
      })}
    </TierCard>
  );
}

function ModelChip({ m, tone }) {
  const isAgree = tone === "agree";
  return (
    <span
      className={"inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10.5px] font-medium"}
      style={{
        borderColor: isAgree ? "rgba(16,185,129,0.4)" : "rgba(244,63,94,0.35)",
        backgroundColor: isAgree ? "rgba(16,185,129,0.08)" : "rgba(244,63,94,0.06)",
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: m.accent }} />
      <span className="text-white/85">{m.label}</span>
      <span className={isAgree ? "text-[#10B981]" : "text-[#F43F5E]"}>{isAgree ? "✓" : "✗"}</span>
    </span>
  );
}

function EvidenceMeterSection() {
  const { t } = useI18n();
  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6 }}
      className="mt-14 min-w-0 max-w-full rounded-3xl border border-white/[0.08] bg-[#0B1120]/80 p-4 backdrop-blur-xl sm:p-6 md:p-8"
      data-testid="evidence-meter"
    >
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-2">{t("results.evidenceMeter")}</div>
          <h3 className="break-words text-xl font-semibold tracking-tight text-white [overflow-wrap:anywhere] md:text-2xl">{t("results.evidenceTitle")}</h3>
          <p className="mt-2 max-w-xl break-words text-[13.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">{t("results.evidenceNote")}</p>
        </div>
        <div className="text-right">
          <div className="text-[10.5px] uppercase tracking-[0.22em] text-white/40">{t("results.totalScore")}</div>
          <div className="text-5xl md:text-6xl font-semibold text-white leading-none mt-1" data-testid="evidence-meter-total">
            {EVIDENCE_METER.total}
            <span className="text-white/40 text-2xl font-normal ml-1">/100</span>
          </div>
        </div>
      </div>

      {/* Big track */}
      <div className="mt-6 relative">
        <div className="h-2.5 rounded-full bg-white/[0.05] overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            whileInView={{ width: `${EVIDENCE_METER.total}%` }}
            viewport={{ once: true }}
            transition={{ duration: 1.2, ease: "easeOut" }}
            className="h-full rounded-full"
            style={{ background: "linear-gradient(90deg, #0066FF, #00E5FF)", boxShadow: "0 0 24px rgba(0,229,255,0.5)" }}
          />
        </div>
        <div className="mt-1.5 flex justify-between text-[10px] font-mono text-white/35">
          <span>0</span><span>25</span><span>50</span><span>75</span><span>100</span>
        </div>
      </div>

      {/* Breakdown */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5" data-testid="evidence-breakdown">
        {EVIDENCE_METER.components.map((c) => (
          <div key={c.key} data-testid={`evidence-${c.key}`}>
            <div className="flex items-center justify-between mb-1.5 text-[13px]">
              <div className="text-white/85 flex items-center gap-2">
                <span className="break-words font-medium [overflow-wrap:anywhere]">{t(`results.evidenceComponents.${c.key}`)}</span>
                <span className="text-[10.5px] text-white/40 font-mono">{t("results.weight")} {c.weight}%</span>
              </div>
              <span className="font-mono text-white/70">{c.value}</span>
            </div>
            <div className="h-1.5 rounded-full bg-white/[0.05] overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                whileInView={{ width: `${c.value}%` }}
                viewport={{ once: true }}
                transition={{ duration: 0.9, ease: "easeOut" }}
                className="h-full rounded-full"
                style={{ backgroundColor: c.key === "citation" ? "#A78BFA" : "#00E5FF" }}
              />
            </div>
            {c.note && (
              <div className="mt-1 break-words text-[11.5px] italic text-[#A78BFA]/80 [overflow-wrap:anywhere]">{t("results.citationLookupSoon")}</div>
            )}
          </div>
        ))}
      </div>
    </motion.section>
  );
}

function ConsensusEvolutionTimeline() {
  const { t } = useI18n();
  return (
    <section className="mt-16 min-w-0 max-w-full" data-testid="evolution-timeline">
      <SectionHeader
        eyebrow={t("results.consensusEvolution")}
        title={t("results.evolutionTitle")}
        body={t("results.evolutionBody")}
      />
      <div className="mt-8 relative">
        {/* connector line — desktop */}
        <div className="hidden md:block absolute left-0 right-0 top-6 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
        <ol className="grid grid-cols-1 md:grid-cols-5 gap-4">
          {EVOLUTION_STEPS.map((s, i) => (
            <motion.li
              key={s.id}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.08 }}
              className="relative"
              data-testid={`evolution-step-${s.id}`}
            >
              <div className="flex md:justify-start items-center gap-3 md:block">
                <div className="relative z-10 w-12 h-12 rounded-full border border-[#00E5FF]/40 bg-[#0B1120] flex items-center justify-center text-[12px] font-mono text-[#00E5FF]" style={{ boxShadow: "0 0 24px rgba(0,229,255,0.15)" }}>
                  0{i + 1}
                </div>
                <div className="md:mt-4">
                  <div className="break-words text-[14px] font-medium tracking-tight text-white [overflow-wrap:anywhere]">{t(`results.evolutionSteps.${s.id}.title`)}</div>
                  <div className="mt-1 break-words text-[12.5px] leading-snug text-white/50 [overflow-wrap:anywhere]">{t(`results.evolutionSteps.${s.id}.body`)}</div>
                </div>
              </div>
              {/* mobile connector */}
              {i < EVOLUTION_STEPS.length - 1 && (
                <div className="md:hidden absolute left-6 top-12 w-px h-6 bg-white/15" />
              )}
            </motion.li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function RationaleCard({ index, title, body, testId }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.5, delay: index * 0.06 }}
      className="min-w-0 max-w-full rounded-2xl border border-white/[0.08] bg-[#0B1120]/70 p-4 backdrop-blur sm:p-6"
      data-testid={testId}
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[10px] font-mono text-[#00E5FF]/80 tracking-widest">0{index}</span>
        <span className="h-px flex-1 bg-white/[0.08]" />
      </div>
      <div className="break-words text-[15px] font-medium leading-snug tracking-tight text-white [overflow-wrap:anywhere]">{title}</div>
      <p className="mt-2 break-words text-[13.5px] leading-relaxed text-white/60 [overflow-wrap:anywhere]">{body}</p>
    </motion.div>
  );
}

function MeterCard({ label, value, accent, testId, delta = 0, icon: Icon }) {
  const IconComp = Icon || Trophy;
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#0B1120] p-4 flex items-center gap-4" data-testid={testId}>
      <div className="w-10 h-10 rounded-xl border flex items-center justify-center" style={{ backgroundColor: `${accent}18`, borderColor: `${accent}55` }}>
        <IconComp className="w-4 h-4" style={{ color: accent }} />
      </div>
      <div className="flex-1">
        <div className="text-[10px] uppercase tracking-[0.22em] text-white/40">{label}</div>
        <div className="text-2xl font-semibold text-white leading-none mt-1 flex items-baseline gap-2">
          {value}<span className="text-white/40 text-sm font-normal">%</span>
          {delta !== 0 && (
            <span className={"text-[11px] font-mono " + (delta > 0 ? "text-[#10B981]" : "text-[#F43F5E]")}>
              {delta > 0 ? "+" : ""}{delta}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function AnimatedMeter({ label, value, accent, testId }) {
  return (
    <div data-testid={testId}>
      <div className="flex items-center justify-between mb-2 text-[12px]">
        <span className="uppercase tracking-[0.22em] text-white/45 text-[10.5px]">{label}</span>
        <span className="font-mono text-white/80">{value}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${value}%` }}
          transition={{ duration: 1.1, ease: "easeOut" }}
          className="h-full rounded-full"
          style={{ backgroundColor: accent, boxShadow: `0 0 14px ${accent}80` }}
        />
      </div>
    </div>
  );
}

function SectionHeader({ eyebrow, title, body, className = "" }) {
  return (
    <div className={"min-w-0 max-w-2xl " + className}>
      <div className="mb-3 break-words text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 [overflow-wrap:anywhere]">{eyebrow}</div>
      <h2 className="break-words text-2xl font-semibold leading-tight tracking-tight text-white [overflow-wrap:anywhere] md:text-3xl">{title}</h2>
      <p className="mt-3 break-words text-[14px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">{body}</p>
    </div>
  );
}
