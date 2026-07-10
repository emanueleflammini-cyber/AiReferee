import { useEffect, useMemo, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
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
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { useQueryState } from "@/lib/QueryContext";
import { useI18n } from "@/lib/i18n";
import {
  MODELS,
  LIVE_MODELS,
  MODEL_STATUS,
  MOCK_RESPONSES,
  MOCK_SCORES,
  MOCK_SUPER_ANSWER,
  MOCK_CONTRIBUTIONS,
  ANALYSIS_STEPS,
  CHALLENGE_STEPS,
  CHALLENGE_OUTCOMES,
  TRANSPARENCY_NOTE,
  CONSENSUS_TIERS,
  EVIDENCE_METER,
  EVOLUTION_STEPS,
  WHY_CHOSE_ANSWER,
  MODEL_DETAILS,
} from "@/lib/mockData";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: "easeOut" } },
};

export default function Results() {
  const navigate = useNavigate();
  const location = useLocation();
  const { query } = useQueryState();
  const { t } = useI18n();
  const prompt = query.prompt || "What is a distributed database and why would I use one?";

  const routeState = location.state || {};
  const mode = routeState.mode || "fresh"; // fresh | reused | updated
  const reuseTopic = routeState.topic;
  const reuseReason = routeState.reason;
  const reuseMatch = routeState.match || routeState.replacedMatch || null;
  const queryId = routeState.queryId || null;
  const answerLanguage = routeState.answerLanguage || "en";

  const [phase, setPhase] = useState(mode === "reused" ? "reveal" : "models");
  const [completedModels, setCompletedModels] = useState(mode === "reused" ? LIVE_MODELS.map((m) => m.id) : []);
  const [analysisStep, setAnalysisStep] = useState(mode === "reused" ? ANALYSIS_STEPS.length : 0);
  const [liveResponses, setLiveResponses] = useState(null); // [{id, label, text, is_mock, ...}]
  const [liveCount, setLiveCount] = useState(0);
  const [totalCost, setTotalCost] = useState(0);
  const [trustedConclusion, setTrustedConclusion] = useState("");
  const [conclusionLoading, setConclusionLoading] = useState(mode !== "reused");

  // Kick off the real comparison on mount (unless we're reusing a cached one)
  useEffect(() => {
    if (!queryId || mode === "reused") return;
    let cancelled = false;
    setConclusionLoading(true);
    axios.post(`${API}/queries/${queryId}/compare`).then((r) => {
      if (cancelled) return;
      setLiveResponses(r.data?.responses || []);
      setLiveCount(r.data?.live_count || 0);
      setTotalCost(r.data?.total_cost_usd || 0);
      setTrustedConclusion(r.data?.trusted_conclusion || "");
      setConclusionLoading(false);
    }).catch((e) => {
      console.warn("Compare failed", e);
      setConclusionLoading(false);
    });
    return () => { cancelled = true; };
  }, [queryId, mode]);

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
        setConclusionLoading(false);
      })
      .catch((e) => {
        console.warn("Fetch reused conclusion failed", e);
        setConclusionLoading(false);
      });
    return () => { cancelled = true; };
  }, [mode, reuseMatch, queryId, answerLanguage]);

  const [challengePhase, setChallengePhase] = useState("idle");
  const [challengeStep, setChallengeStep] = useState(0);
  const [challengeOutcome, setChallengeOutcome] = useState(null);

  useEffect(() => {
    if (phase !== "models") return;
    const timers = LIVE_MODELS.map((m, i) =>
      setTimeout(() => {
        setCompletedModels((prev) => (prev.includes(m.id) ? prev : [...prev, m.id]));
        if (i === LIVE_MODELS.length - 1) {
          setTimeout(() => setPhase("analysis"), 600);
        }
      }, 900 + i * 900),
    );
    return () => timers.forEach(clearTimeout);
  }, [phase]);

  useEffect(() => {
    if (phase !== "analysis") return;
    if (analysisStep >= ANALYSIS_STEPS.length) {
      const t = setTimeout(() => setPhase("reveal"), 500);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setAnalysisStep((s) => s + 1), 550);
    return () => clearTimeout(t);
  }, [phase, analysisStep]);
  useEffect(() => {
    if (challengePhase !== "running") return;
    if (challengeStep >= CHALLENGE_STEPS.length) {
      const t = setTimeout(() => {
        setChallengeOutcome(CHALLENGE_OUTCOMES.strengthened);
        setChallengePhase("done");
      }, 500);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setChallengeStep((s) => s + 1), 620);
    return () => clearTimeout(t);
  }, [challengePhase, challengeStep]);

  const currentConfidence = challengeOutcome ? challengeOutcome.newConfidence : MOCK_SCORES.confidence;

  return (
    <div className="relative min-h-screen bg-[#060A14] text-white overflow-hidden" data-testid="results-page">
      <div className="pointer-events-none absolute inset-0 opacity-60 grid-pattern" />
      <NavBar variant="results" />

      <main className="relative mx-auto max-w-6xl px-5 md:px-8 pt-10 md:pt-14 pb-24">
        <button
          onClick={() => navigate("/")}
          data-testid="back-home-button"
          className="inline-flex items-center gap-1.5 text-[13px] text-white/50 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> {t("results.backPrompt")}
        </button>

        <div className="mt-4 max-w-3xl">
          <div className="text-[11px] uppercase tracking-[0.2em] text-white/40 mb-2">{t("results.yourQuestion")}</div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight leading-snug" data-testid="results-question">
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
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {LIVE_MODELS.map((m) => {
                  const done = completedModels.includes(m.id);
                  return (
                    <div
                      key={m.id}
                      data-testid={`load-${m.id}`}
                      className={
                        "relative rounded-2xl border p-5 transition-colors " +
                        (done ? "border-white/15 bg-white/[0.04]" : "border-white/[0.06] bg-[#0B1120]")
                      }
                    >
                      <span className="absolute left-0 top-5 bottom-5 w-[3px] rounded-r" style={{ backgroundColor: m.accent, boxShadow: `0 0 20px ${m.accent}80` }} />
                      <div className="flex items-center justify-between pl-3">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium" style={{ backgroundColor: `${m.accent}18`, borderColor: `${m.accent}55`, color: m.accent }}>
                            {m.initials}
                          </div>
                          <div>
                            <div className="text-[14.5px] font-medium text-white">{m.label}</div>
                            <div className="text-[11.5px] text-white/45">{m.codename} · {m.provider}</div>
                          </div>
                        </div>
                        <div className="text-[12px] flex items-center gap-2">
                          {done ? (
                            <span className="inline-flex items-center gap-1.5 text-[#10B981]" data-testid={`load-${m.id}-complete`}>
                              <Check className="w-3.5 h-3.5" /> {t("results.complete")}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-white/50" data-testid={`load-${m.id}-thinking`}>
                              <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t("results.thinking")}
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
                    className="mt-6 rounded-2xl border border-[#00E5FF]/25 bg-[#00E5FF]/[0.04] p-6"
                    data-testid="analysis-phase"
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
                      {ANALYSIS_STEPS.slice(0, analysisStep).map((s, i) => (
                        <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.35 }} className="flex items-center gap-2 text-[13.5px] text-white/80" data-testid={`analysis-step-${i}`}>
                          <Check className="w-3.5 h-3.5 text-[#10B981]" /> {s}
                        </motion.li>
                      ))}
                      {analysisStep < ANALYSIS_STEPS.length && (
                        <li className="flex items-center gap-2 text-[13.5px] text-white/60">
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-[#00E5FF]" /> {ANALYSIS_STEPS[analysisStep]}
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
            conclusionLoading={conclusionLoading}
            answerLanguage={answerLanguage}
            onChallenge={() => {
              if (challengePhase === "idle") {
                setChallengeStep(0);
                setChallengeOutcome(null);
                setChallengePhase("running");
              }
            }}
            onSeeDebate={() => navigate("/debate")}
          />
        )}
      </main>
    </div>
  );
}

function RevealSection({ currentConfidence, challengePhase, challengeStep, challengeOutcome, onChallenge, onSeeDebate, liveResponses, liveCount, totalCost, trustedConclusion, conclusionLoading, answerLanguage }) {
  const modelById = useMemo(() => Object.fromEntries(MODELS.map((m) => [m.id, m])), []);
  const { t } = useI18n();
  const liveById = useMemo(() => {
    if (!liveResponses) return {};
    return Object.fromEntries(liveResponses.map((r) => [r.id, r]));
  }, [liveResponses]);

  return (
    <>
      {/* Scores strip */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-3"
      >
        <MeterCard label={t("results.confidence")} value={currentConfidence} accent="#00E5FF" testId="score-confidence" icon={Gauge} delta={challengeOutcome ? currentConfidence - MOCK_SCORES.confidence : 0} />
        <MeterCard label={t("results.consensusLevel")} value={MOCK_SCORES.consensus} accent="#10B981" testId="score-consensus" icon={Trophy} />
        <MeterCard label={t("results.trust")} value={MOCK_SCORES.trust} accent="#0066FF" testId="score-trust" icon={ShieldCheck} />
      </motion.div>

      {/* Live indicator strip */}
      {liveResponses && (
        <div className="mt-6 flex flex-wrap items-center gap-2 text-[12px] text-white/60" data-testid="live-status">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[#10B981]/40 bg-[#10B981]/[0.08] px-2.5 py-0.5 text-[#10B981]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#10B981]" />
            {liveCount} LIVE model{liveCount === 1 ? "" : "s"}
          </span>
          {liveResponses.some((r) => r.is_mock && !r.error) && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#A78BFA]/40 bg-[#A78BFA]/[0.08] px-2.5 py-0.5 text-[#A78BFA]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#A78BFA]" />
              {liveResponses.filter((r) => r.is_mock && !r.error).length} MOCKED
            </span>
          )}
          {liveResponses.some((r) => r.is_mock && r.error) && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#F43F5E]/50 bg-[#F43F5E]/[0.08] px-2.5 py-0.5 text-[#F43F5E]" data-testid="fallback-summary">
              <span className="w-1.5 h-1.5 rounded-full bg-[#F43F5E]" />
              {liveResponses.filter((r) => r.is_mock && r.error).length} FALLBACK
            </span>
          )}
          {typeof totalCost === "number" && totalCost > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-0.5 text-white/70 font-mono" data-testid="total-cost">
              ~${totalCost.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}
            </span>
          )}
          <span className="text-white/40">Grok, Mistral and Claude are on the roadmap — enable them in <code className="font-mono text-white/60">backend/.env</code> to light up more slots.</span>
        </div>
      )}

      {/* Model cards — now expandable */}
      <motion.div
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } } }}
        className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-5"
        data-testid="models-grid"
      >
        {MODELS.map((m) => {
          if (m.status !== MODEL_STATUS.LIVE) {
            return <ComingSoonModelCard key={m.id} model={m} />;
          }
          const live = liveById[m.id];
          const responseText = live?.text || MOCK_RESPONSES[m.id];
          const isMock = live ? live.is_mock : true;
          return (
            <ExpandableModelCard
              key={m.id}
              model={m}
              codename={live?.codename || m.codename}
              response={responseText}
              details={MODEL_DETAILS[m.id]}
              contribution={MOCK_CONTRIBUTIONS.find((c) => c.modelId === m.id)?.pct || 0}
              latencyMs={live?.latency_ms || m.latencyMs}
              tokens={live?.total_tokens || m.tokens}
              inputTokens={live?.input_tokens}
              outputTokens={live?.output_tokens}
              costUsd={live?.cost_usd}
              modelUsed={live?.model_used}
              isMock={isMock}
              error={live?.error}
            />
          );
        })}
      </motion.div>

      {/* Trusted Conclusion */}
      <motion.section
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: "easeOut", delay: 0.1 }}
        className="relative mt-12 rounded-3xl overflow-hidden border border-[#0066FF]/40"
        data-testid="trusted-conclusion-card"
      >
        <div className="absolute inset-0 super-glow" />
        <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-[#00E5FF]/60 to-transparent" />
        <div className="relative p-8 md:p-10">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-9 h-9 rounded-xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-[#00E5FF]" />
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">{t("results.refereeVerdict")}</div>
              <h2 className="text-2xl md:text-3xl font-semibold tracking-tight text-white">{t("results.trustedConclusion")}</h2>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
            <AnimatedMeter label={t("results.confidenceScore")} value={currentConfidence} accent="#00E5FF" testId="meter-confidence" />
            <AnimatedMeter label={t("results.consensusLevel")} value={MOCK_SCORES.consensus} accent="#10B981" testId="meter-consensus" />
          </div>

          <div className="text-[15.5px] md:text-[16.5px] leading-[1.75] text-white/85 whitespace-pre-line" data-testid="trusted-conclusion-body" data-answer-language={answerLanguage}>
            {conclusionLoading ? (
              <span className="inline-flex items-center gap-2 text-white/50 text-[14px]" data-testid="trusted-conclusion-loading">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF] animate-pulse" />
                {t("results.synthesizing")}
              </span>
            ) : (trustedConclusion || (
              <span className="text-white/50 text-[14px] italic" data-testid="trusted-conclusion-empty">
                {t("results.noConclusion")}
              </span>
            ))}
          </div>

          <AnimatePresence>
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
                      <Swords className="w-3.5 h-3.5" /> Challenge in progress
                    </div>
                    <ul className="space-y-2">
                      {CHALLENGE_STEPS.slice(0, challengeStep).map((s, i) => (
                        <li key={i} className="flex items-center gap-2 text-[13.5px] text-white/80" data-testid={`challenge-step-${i}`}>
                          <Check className="w-3.5 h-3.5 text-[#10B981]" /> {s}
                        </li>
                      ))}
                      {challengeStep < CHALLENGE_STEPS.length && (
                        <li className="flex items-center gap-2 text-[13.5px] text-white/60">
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-[#F59E0B]" /> {CHALLENGE_STEPS[challengeStep]}
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
          </AnimatePresence>

          <div className="mt-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-6 border-t border-white/[0.08]">
            <div className="flex flex-wrap items-center gap-3 text-[12px] text-white/50">
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF]" /> {t("results.synthesizedFromLive", { n: LIVE_MODELS.length })}
              </span>
              <span>·</span>
              <span>{t("results.confidence")} {currentConfidence}%</span>
              <span>·</span>
              <span>{t("results.consensus")} {MOCK_SCORES.consensus}%</span>
            </div>
            <button
              onClick={onChallenge}
              disabled={challengePhase === "running"}
              data-testid="challenge-conclusion-button"
              className="group inline-flex items-center gap-2 rounded-full border border-[#F59E0B]/40 bg-[#F59E0B]/[0.08] text-[#F59E0B] hover:bg-[#F59E0B]/[0.14] px-5 py-2.5 text-[13px] font-medium transition-colors disabled:opacity-70"
            >
              <Swords className="w-4 h-4" />
              {challengePhase === "idle" ? t("results.challengeConclusion") : challengePhase === "running" ? t("results.challenging") : t("results.challengeAgain")}
            </button>
          </div>
        </div>
      </motion.section>

      {/* Why this conclusion? — 4 tier cards */}
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
        {WHY_CHOSE_ANSWER.map((w, i) => (
          <RationaleCard key={i} index={i + 1} title={w.title} body={w.body} testId={`rationale-${i}`} />
        ))}
      </div>

      {/* View Full Debate CTA */}
      <div className="mt-10 flex justify-center">
        <button
          onClick={onSeeDebate}
          data-testid="view-full-debate-button"
          className="group inline-flex items-center gap-2 rounded-full bg-white text-[#060A14] font-medium px-6 py-3 text-[14px] hover:bg-white/90 transition-colors"
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

      {/* Transparency */}
      <div
        className="mt-8 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5 flex gap-3 items-start"
        data-testid="transparency-note"
      >
        <Info className="w-4 h-4 text-white/50 mt-0.5 flex-shrink-0" />
        <p className="text-[13px] text-white/60 leading-relaxed">{TRANSPARENCY_NOTE}</p>
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
            <span className="text-[11px] uppercase tracking-[0.2em] text-white/40 font-mono" data-testid="reuse-topic-badge">{t(`results.topic.${topic}`) === `results.topic.${topic}` ? topic : t(`results.topic.${topic}`)}</span>
          )}
        </div>
        <div className="mt-1 text-[12.5px] text-white/60 leading-relaxed">
          {isReused ? t("results.reusedExplainer") : t("results.updatedExplainer")}
          {match && (
            <span className="text-white/40"> · {t("results.previousQuestion")}: <span className="italic text-white/60">“{match.prompt}”</span></span>
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
      className="relative rounded-2xl border border-dashed border-white/[0.12] bg-[#0B1120]/60 opacity-90"
      style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)" }}
    >
      <span className={`absolute left-0 top-6 bottom-6 w-[3px] rounded-r ${m.accentClass || ""}`} style={{ backgroundColor: `${m.accent}55` }} />
      <div className="flex items-start justify-between p-6 pl-9 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium flex-shrink-0"
            style={{ backgroundColor: `${m.accent}12`, borderColor: `${m.accent}40`, color: m.accent }}
          >
            {m.initials}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-[14.5px] font-medium text-white/85">{m.label}</div>
              {isPremium && (
                <span className="text-[11px] text-[#FBBF24]" aria-hidden data-testid={`card-${m.id}-premium-star`}>★</span>
              )}
              <span
                data-testid={`card-${m.id}-status`}
                className={"inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-[0.14em] uppercase " + accentBadge}
              >
                {label}
              </span>
            </div>
            <div className="text-[11.5px] text-white/40">{m.codename} · {m.provider}</div>
          </div>
        </div>
      </div>
      <div className="px-6 pl-9 pb-6 text-[13.5px] leading-[1.65] text-white/50 italic" data-testid={`response-${m.id}`}>
        {isPremium
          ? "Claude will join the panel for Premium subscribers. When Premium launches, this slot will contribute to a three-model Trusted Conclusion (GPT + Gemini + Claude)."
          : `${m.label} is on the roadmap. The provider registry is ready — this slot will go live as soon as the API is wired.`}
      </div>
    </motion.article>
  );
}

function ExpandableModelCard({ model: m, response, details, contribution, codename, latencyMs, tokens, isMock, error, inputTokens, outputTokens, costUsd, modelUsed }) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  const displayCodename = modelUsed || codename || m.codename;
  const showLive = isMock === false;
  const isFallback = isMock === true && !!error;

  let badge;
  if (showLive) {
    badge = (
      <span className="text-[9.5px] font-mono tracking-wider rounded-full border border-[#10B981]/40 bg-[#10B981]/[0.1] text-[#10B981] px-1.5 py-0.5" data-testid={`card-${m.id}-live`}>{t("badge.live")}</span>
    );
  } else if (isFallback) {
    badge = (
      <span className="text-[9.5px] font-mono tracking-wider rounded-full border border-[#F43F5E]/50 bg-[#F43F5E]/[0.1] text-[#F43F5E] px-1.5 py-0.5" title={error} data-testid={`card-${m.id}-fallback`}>{t("badge.fallback")}</span>
    );
  } else {
    badge = (
      <span className="text-[9.5px] font-mono tracking-wider rounded-full border border-[#A78BFA]/40 bg-[#A78BFA]/[0.1] text-[#A78BFA] px-1.5 py-0.5" data-testid={`card-${m.id}-mocked`}>{t("badge.mocked")}</span>
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
      className="group relative rounded-2xl border border-white/[0.08] bg-[#0B1120] hover:border-white/20 transition-colors"
      style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)" }}
    >
      <span className={`absolute left-0 top-6 bottom-6 w-[3px] rounded-r ${m.accentClass}`} />
      <header className="flex items-start justify-between p-6 pl-9 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium flex-shrink-0" style={{ backgroundColor: `${m.accent}18`, borderColor: `${m.accent}55`, color: m.accent }}>
            {m.initials}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-[14.5px] font-medium text-white">{m.label}</div>
              {badge}
            </div>
            <div className="text-[11.5px] text-white/45" data-testid={`card-${m.id}-model`}>{displayCodename} · {m.provider}</div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-[11px] font-mono text-white/40 flex-shrink-0">
          <span data-testid={`card-${m.id}-confidence`}>conf {details.confidence}%</span>
          <span>·</span>
          <span data-testid={`card-${m.id}-contribution`}>contrib {contribution}%</span>
        </div>
      </header>
      <div className="px-6 pl-9 text-[14.5px] leading-[1.65] text-white/75 whitespace-pre-line" data-testid={`response-${m.id}`}>
        {response}
      </div>
      {isFallback && error && (
        <div className="px-6 pl-9 mt-3 text-[11.5px] text-[#F43F5E]/80" data-testid={`card-${m.id}-error`}>
          Provider error · {error}. Using fallback text.
        </div>
      )}
      <div className="px-6 pl-9 mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-mono text-white/40" data-testid={`card-${m.id}-stats`}>
        <span>{latencyMs ?? m.latencyMs}ms</span>
        <span>·</span>
        <span>in {inputTokens ?? 0}</span>
        <span>·</span>
        <span>out {outputTokens ?? 0}</span>
        <span>·</span>
        <span title="Estimated cost — see /app/backend/providers/base.py for rates">~{formatCost(costUsd || 0)}</span>
      </div>
      <button
        onClick={() => setOpen((v) => !v)}
        data-testid={`expand-${m.id}`}
        className="w-full mt-5 border-t border-white/[0.06] px-6 py-3 flex items-center justify-between text-[12.5px] text-white/60 hover:text-white hover:bg-white/[0.02] transition-colors rounded-b-2xl"
      >
        <span className="flex items-center gap-2">
          <ScatterChart className="w-3.5 h-3.5" />
          {open ? t("results.hideBreakdown") : t("results.showBreakdown")}
        </span>
        <ChevronDown className={"w-4 h-4 transition-transform " + (open ? "rotate-180" : "")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
            className="overflow-hidden"
            data-testid={`details-${m.id}`}
          >
            <div className="px-6 pl-9 pb-6 space-y-5">
              <ModelDetailBlock title="Main arguments" items={details.mainArguments} accent={m.accent} />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <ModelDetailBlock title="Strengths"  items={details.strengths}  accent="#10B981" />
                <ModelDetailBlock title="Weaknesses" items={details.weaknesses} accent="#F43F5E" />
              </div>
              <div className="pt-2">
                <div className="flex items-center justify-between mb-1.5 text-[12px] text-white/60">
                  <span className="uppercase tracking-[0.2em] text-[10.5px]">Confidence</span>
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
    <div>
      <div className="text-[10.5px] uppercase tracking-[0.22em] text-white/45 mb-2">{title}</div>
      <ul className="space-y-1.5">
        {items.map((t, i) => (
          <li key={i} className="flex gap-2 text-[13px] text-white/75 leading-relaxed">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: accent }} />
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TierCard({ accent, label, badge, whyLabel, why, testId, children }) {
  return (
    <div
      className="relative rounded-2xl border p-6 backdrop-blur-xl"
      style={{
        borderColor: `${accent}40`,
        background: `linear-gradient(180deg, ${accent}0d, rgba(11,17,32,0.75) 60%)`,
        boxShadow: `inset 0 1px 0 ${accent}22`,
      }}
      data-testid={testId}
    >
      <div className="flex items-start justify-between mb-4 gap-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${accent}20`, border: `1px solid ${accent}55` }}>
            {badge}
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em]" style={{ color: accent }}>{whyLabel}</div>
            <div className="text-[16px] font-semibold text-white tracking-tight">{label}</div>
          </div>
        </div>
      </div>
      {why && (
        <p className="text-[12.5px] text-white/50 leading-relaxed mb-4">{why}</p>
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
          <div className="text-[13.5px] text-white/85 leading-relaxed">{it.text}</div>
          <div className="mt-1.5 text-[11.5px] text-white/40 italic">{it.why}</div>
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
            <div className="text-[13.5px] text-white/85 leading-relaxed flex-1">{it.text}</div>
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
          <div className="text-[11.5px] text-white/45 italic">{it.why}</div>
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
                    {m.initials}
                  </div>
                  <div className="flex-1">
                    <div className="text-[12px] font-medium text-white">{m.label}</div>
                    <div className="text-[13px] text-white/75 leading-relaxed mt-0.5">“{p.stance}”</div>
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
              <div className="flex items-center gap-2 text-[12px] text-white/70">
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: m.accent }} />
                <span className="font-medium text-white">{m.label}</span>
                <span className="text-white/40">only</span>
              </div>
              <span className="text-[10.5px] font-mono px-1.5 py-0.5 rounded-md border border-[#A78BFA]/40 text-[#A78BFA]">{it.label}</span>
            </div>
            <div className="text-[13.5px] text-white/85 leading-relaxed">{it.text}</div>
            <div className="mt-1.5 text-[11.5px] text-white/45 italic">Why it may still be valuable: {it.value}</div>
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
  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6 }}
      className="mt-14 rounded-3xl border border-white/[0.08] bg-[#0B1120]/80 backdrop-blur-xl p-6 md:p-8"
      data-testid="evidence-meter"
    >
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-2">Evidence Meter</div>
          <h3 className="text-xl md:text-2xl font-semibold tracking-tight text-white">How defensible is this answer?</h3>
          <p className="mt-2 text-[13.5px] text-white/55 max-w-xl leading-relaxed">{EVIDENCE_METER.note}</p>
        </div>
        <div className="text-right">
          <div className="text-[10.5px] uppercase tracking-[0.22em] text-white/40">Total score</div>
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
                <span className="font-medium">{c.label}</span>
                <span className="text-[10.5px] text-white/40 font-mono">weight {c.weight}%</span>
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
              <div className="mt-1 text-[11.5px] text-[#A78BFA]/80 italic">{c.note}</div>
            )}
          </div>
        ))}
      </div>
    </motion.section>
  );
}

function ConsensusEvolutionTimeline() {
  return (
    <section className="mt-16" data-testid="evolution-timeline">
      <SectionHeader
        eyebrow="Consensus Evolution"
        title="How Referee arrived here"
        body="From your question to the final verdict — five phases, each visible."
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
                  <div className="text-[14px] font-medium text-white tracking-tight">{s.title}</div>
                  <div className="text-[12.5px] text-white/50 leading-snug mt-1">{s.body}</div>
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
      className="rounded-2xl border border-white/[0.08] bg-[#0B1120]/70 backdrop-blur p-6"
      data-testid={testId}
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[10px] font-mono text-[#00E5FF]/80 tracking-widest">0{index}</span>
        <span className="h-px flex-1 bg-white/[0.08]" />
      </div>
      <div className="text-[15px] font-medium text-white tracking-tight leading-snug">{title}</div>
      <p className="mt-2 text-[13.5px] text-white/60 leading-relaxed">{body}</p>
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
    <div className={"max-w-2xl " + className}>
      <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-3">{eyebrow}</div>
      <h2 className="text-2xl md:text-3xl font-semibold tracking-tight text-white leading-tight">{title}</h2>
      <p className="mt-3 text-[14px] text-white/55 leading-relaxed">{body}</p>
    </div>
  );
}
