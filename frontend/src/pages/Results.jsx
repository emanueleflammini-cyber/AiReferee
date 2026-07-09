import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { useQueryState } from "@/lib/QueryContext";
import {
  MODELS,
  MOCK_RESPONSES,
  MOCK_SCORES,
  MOCK_SUPER_ANSWER,
  MOCK_WHY,
  MOCK_CONTRIBUTIONS,
  ANALYSIS_STEPS,
  CHALLENGE_STEPS,
  CHALLENGE_OUTCOMES,
  TRANSPARENCY_NOTE,
} from "@/lib/mockData";

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: "easeOut" } },
};

// Phases: "models" (each model thinks -> complete) -> "analysis" (consensus steps) -> "reveal"
// Challenge phases: "idle" -> "running" -> "done"

export default function Results() {
  const navigate = useNavigate();
  const { query } = useQueryState();
  const prompt = query.prompt || "What is a distributed database and why would I use one?";

  const [phase, setPhase] = useState("models");
  const [completedModels, setCompletedModels] = useState([]); // list of model ids
  const [analysisStep, setAnalysisStep] = useState(0);

  const [challengePhase, setChallengePhase] = useState("idle");
  const [challengeStep, setChallengeStep] = useState(0);
  const [challengeOutcome, setChallengeOutcome] = useState(null);

  // Phase 1: models finish sequentially
  useEffect(() => {
    if (phase !== "models") return;
    const timers = MODELS.map((m, i) =>
      setTimeout(() => {
        setCompletedModels((prev) => (prev.includes(m.id) ? prev : [...prev, m.id]));
        if (i === MODELS.length - 1) {
          setTimeout(() => setPhase("analysis"), 600);
        }
      }, 900 + i * 900),
    );
    return () => timers.forEach(clearTimeout);
  }, [phase]);

  // Phase 2: consensus analysis steps
  useEffect(() => {
    if (phase !== "analysis") return;
    if (analysisStep >= ANALYSIS_STEPS.length) {
      const t = setTimeout(() => setPhase("reveal"), 500);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setAnalysisStep((s) => s + 1), 550);
    return () => clearTimeout(t);
  }, [phase, analysisStep]);

  // Challenge phase steps
  useEffect(() => {
    if (challengePhase !== "running") return;
    if (challengeStep >= CHALLENGE_STEPS.length) {
      // pick outcome — deterministic: strengthened (feels more product-like as default)
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
          <ArrowLeft className="w-3.5 h-3.5" /> Back to prompt
        </button>

        <div className="mt-4 max-w-3xl">
          <div className="text-[11px] uppercase tracking-[0.2em] text-white/40 mb-2">Your question</div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight leading-snug" data-testid="results-question">
            “{prompt}”
          </h1>
        </div>

        {/* Phase 1 + 2 : loading */}
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
              {/* Model progress */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {MODELS.map((m) => {
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
                          <div
                            className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium"
                            style={{ backgroundColor: `${m.accent}18`, borderColor: `${m.accent}55`, color: m.accent }}
                          >
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
                              <Check className="w-3.5 h-3.5" /> Complete
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-white/50" data-testid={`load-${m.id}-thinking`}>
                              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Thinking...
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Analysis */}
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
                        <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">Consensus Analysis</div>
                        <div className="text-[14px] text-white">Comparing reasoning across four models</div>
                      </div>
                    </div>
                    <ul className="space-y-2">
                      {ANALYSIS_STEPS.slice(0, analysisStep).map((s, i) => (
                        <motion.li
                          key={i}
                          initial={{ opacity: 0, x: -6 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ duration: 0.35 }}
                          className="flex items-center gap-2 text-[13.5px] text-white/80"
                          data-testid={`analysis-step-${i}`}
                        >
                          <Check className="w-3.5 h-3.5 text-[#10B981]" />
                          {s}
                        </motion.li>
                      ))}
                      {analysisStep < ANALYSIS_STEPS.length && (
                        <li className="flex items-center gap-2 text-[13.5px] text-white/60">
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-[#00E5FF]" />
                          {ANALYSIS_STEPS[analysisStep]}
                        </li>
                      )}
                    </ul>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Phase 3 : reveal */}
        {phase === "reveal" && (
          <RevealSection
            prompt={prompt}
            currentConfidence={currentConfidence}
            challengePhase={challengePhase}
            challengeStep={challengeStep}
            challengeOutcome={challengeOutcome}
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

function RevealSection({ currentConfidence, challengePhase, challengeStep, challengeOutcome, onChallenge, onSeeDebate }) {
  const modelById = useMemo(() => Object.fromEntries(MODELS.map((m) => [m.id, m])), []);

  return (
    <>
      {/* Scores strip */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-3"
      >
        <MeterCard label="Confidence" value={currentConfidence} accent="#00E5FF" testId="score-confidence" delta={challengeOutcome ? currentConfidence - MOCK_SCORES.confidence : 0} />
        <MeterCard label="Consensus Level" value={MOCK_SCORES.consensus} accent="#10B981" testId="score-consensus" />
        <MeterCard label="Trust" value={MOCK_SCORES.trust} accent="#0066FF" testId="score-trust" secondaryIcon={ShieldCheck} />
      </motion.div>

      {/* Models grid */}
      <motion.div
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } } }}
        className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-5"
        data-testid="models-grid"
      >
        {MODELS.map((m) => (
          <motion.article
            key={m.id}
            variants={item}
            data-testid={`card-${m.id}`}
            className="group relative rounded-2xl border border-white/[0.08] bg-[#0B1120] p-6 hover:border-white/20 transition-colors"
            style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)" }}
          >
            <span className={`absolute left-0 top-6 bottom-6 w-[3px] rounded-r ${m.accentClass}`} />
            <header className="flex items-center justify-between mb-4 pl-3">
              <div className="flex items-center gap-3">
                <div
                  className="w-9 h-9 rounded-xl border flex items-center justify-center text-[12px] font-medium"
                  style={{ backgroundColor: `${m.accent}18`, borderColor: `${m.accent}55`, color: m.accent }}
                >
                  {m.initials}
                </div>
                <div>
                  <div className="text-[14.5px] font-medium text-white">{m.label}</div>
                  <div className="text-[11.5px] text-white/45">{m.codename} · {m.provider}</div>
                </div>
              </div>
              <div className="flex items-center gap-3 text-[11px] font-mono text-white/40">
                <span>{m.latencyMs}ms</span><span>·</span><span>{m.tokens} tok</span>
              </div>
            </header>
            <div className="pl-3 text-[14.5px] leading-[1.65] text-white/75 whitespace-pre-line" data-testid={`response-${m.id}`}>
              {MOCK_RESPONSES[m.id]}
            </div>
          </motion.article>
        ))}
      </motion.div>

      {/* Agreement / Disagreement / Uncertainty */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
        <PointList title="Key Agreements"     icon={Check}       accent="#10B981" items={MOCK_SCORES.agreementPoints}    testId="agreement-list" />
        <PointList title="Key Disagreements"  icon={MinusCircle} accent="#F43F5E" items={MOCK_SCORES.disagreementPoints} testId="disagreement-list" />
        <PointList title="Remaining Uncertainty" icon={HelpCircle} accent="#F59E0B" items={MOCK_SCORES.uncertaintyPoints}  testId="uncertainty-list" />
      </div>

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
              <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">Referee verdict</div>
              <h2 className="text-2xl md:text-3xl font-semibold tracking-tight text-white">Trusted Conclusion</h2>
            </div>
          </div>

          {/* Confidence + Consensus meters */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
            <AnimatedMeter label="Confidence Score"  value={currentConfidence} accent="#00E5FF" testId="meter-confidence" />
            <AnimatedMeter label="Consensus Level"   value={MOCK_SCORES.consensus} accent="#10B981" testId="meter-consensus" />
          </div>

          <div className="text-[15.5px] md:text-[16.5px] leading-[1.75] text-white/85 whitespace-pre-line" data-testid="trusted-conclusion-body">
            {MOCK_SUPER_ANSWER}
          </div>

          {/* Why this conclusion */}
          <div className="mt-8 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="why-conclusion">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-3">
              <Info className="w-3.5 h-3.5" /> Why this conclusion?
            </div>
            <ul className="space-y-2">
              {MOCK_WHY.map((t, i) => (
                <li key={i} className="flex gap-2 text-[13.5px] text-white/70 leading-relaxed">
                  <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[#00E5FF] flex-shrink-0" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Challenge outcome (if any) */}
          <AnimatePresence>
            {challengePhase !== "idle" && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="mt-6"
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

          {/* CTA row */}
          <div className="mt-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-6 border-t border-white/[0.08]">
            <div className="flex flex-wrap items-center gap-3 text-[12px] text-white/50">
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF]" /> Synthesized from 4 models
              </span>
              <span>·</span>
              <span>Confidence {currentConfidence}%</span>
              <span>·</span>
              <span>Consensus {MOCK_SCORES.consensus}%</span>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={onChallenge}
                disabled={challengePhase === "running"}
                data-testid="challenge-conclusion-button"
                className="group inline-flex items-center gap-2 rounded-full border border-[#F59E0B]/40 bg-[#F59E0B]/[0.08] text-[#F59E0B] hover:bg-[#F59E0B]/[0.14] px-5 py-2.5 text-[13px] font-medium transition-colors disabled:opacity-70"
              >
                <Swords className="w-4 h-4" />
                {challengePhase === "idle" ? "Challenge Conclusion" : challengePhase === "running" ? "Challenging..." : "Challenge again"}
              </button>
              <button
                onClick={onSeeDebate}
                data-testid="see-full-debate-button"
                className="group inline-flex items-center gap-2 rounded-full bg-white text-[#060A14] font-medium px-5 py-2.5 text-[13px] hover:bg-white/90 transition-colors"
                style={{ boxShadow: "0 20px 50px -18px rgba(0,229,255,0.6)" }}
              >
                <MessagesSquare className="w-4 h-4" />
                See Full Debate
                <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
              </button>
            </div>
          </div>
        </div>
      </motion.section>

      {/* Model contribution */}
      <motion.section
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.15 }}
        className="mt-10 rounded-2xl border border-white/[0.08] bg-[#0B1120] p-6 md:p-8"
        data-testid="contribution-card"
      >
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-2">
          <BarChart3 className="w-3.5 h-3.5" /> Model Contribution
        </div>
        <h3 className="text-xl font-semibold tracking-tight text-white">How each model shaped the conclusion</h3>
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
                    animate={{ width: `${c.pct}%` }}
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

function MeterCard({ label, value, accent, testId, delta = 0, secondaryIcon: SIcon }) {
  return (
    <div
      className="rounded-2xl border border-white/[0.08] bg-[#0B1120] p-4 flex items-center gap-4"
      data-testid={testId}
    >
      <div
        className="w-10 h-10 rounded-xl border flex items-center justify-center"
        style={{ backgroundColor: `${accent}18`, borderColor: `${accent}55` }}
      >
        {SIcon ? <SIcon className="w-4 h-4" style={{ color: accent }} /> : <Trophy className="w-4 h-4" style={{ color: accent }} />}
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

function PointList({ title, icon: Icon, accent, items, testId }) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#0B1120] p-6" data-testid={testId}>
      <div className="flex items-center gap-2 mb-4">
        <div
          className="w-7 h-7 rounded-md flex items-center justify-center"
          style={{ backgroundColor: `${accent}1a`, border: `1px solid ${accent}33` }}
        >
          <Icon className="w-3.5 h-3.5" style={{ color: accent }} />
        </div>
        <h3 className="text-[14.5px] font-medium text-white tracking-tight">{title}</h3>
      </div>
      <ul className="space-y-3">
        {items.map((t, i) => (
          <li key={i} className="flex gap-3 text-[13.5px] leading-relaxed text-white/70">
            <span className="mt-2 w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: accent }} />
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
