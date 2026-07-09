import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  MinusCircle,
  Sparkles,
  Trophy,
  ShieldCheck,
  MessagesSquare,
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { useQueryState } from "@/lib/QueryContext";
import { MODELS, MOCK_RESPONSES, MOCK_SCORES, MOCK_SUPER_ANSWER } from "@/lib/mockData";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: "easeOut" } },
};

export default function Results() {
  const navigate = useNavigate();
  const { query } = useQueryState();
  const prompt = query.prompt || "What is a distributed database and why would I use one?";

  return (
    <div className="relative min-h-screen bg-[#060A14] text-white overflow-hidden" data-testid="results-page">
      <div className="pointer-events-none absolute inset-0 opacity-60 grid-pattern" />
      <NavBar variant="results" />

      <main className="relative mx-auto max-w-6xl px-5 md:px-8 pt-10 md:pt-14 pb-24">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="space-y-4"
        >
          <button
            onClick={() => navigate("/")}
            data-testid="back-home-button"
            className="inline-flex items-center gap-1.5 text-[13px] text-white/50 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to prompt
          </button>
          <div className="flex items-start justify-between gap-6 flex-wrap">
            <div className="max-w-3xl">
              <div className="text-[11px] uppercase tracking-[0.2em] text-white/40 mb-2">Your question</div>
              <h1 className="text-2xl md:text-3xl font-semibold tracking-tight leading-snug" data-testid="results-question">
                “{prompt}”
              </h1>
            </div>
            <div className="flex gap-3">
              <ScorePill icon={Trophy} label="Consensus" value={MOCK_SCORES.consensus} accent="#00E5FF" testId="score-consensus" />
              <ScorePill icon={ShieldCheck} label="Trust" value={MOCK_SCORES.trust} accent="#10B981" testId="score-trust" />
            </div>
          </div>
        </motion.div>

        {/* Models grid */}
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="mt-10 grid grid-cols-1 md:grid-cols-2 gap-5"
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
              {/* Accent bar */}
              <span className={`absolute left-0 top-6 bottom-6 w-[3px] rounded-r ${m.accentClass}`} />
              <header className="flex items-center justify-between mb-4 pl-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.18em] text-white/40">{m.label}</div>
                  <div className="text-[15px] font-medium text-white mt-1">
                    {m.codename} <span className="text-white/40 font-normal"> · {m.provider}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-[11px] font-mono text-white/40">
                  <span>{m.latencyMs}ms</span>
                  <span>·</span>
                  <span>{m.tokens} tok</span>
                </div>
              </header>
              <div className="pl-3 text-[14.5px] leading-[1.65] text-white/75 whitespace-pre-line" data-testid={`response-${m.id}`}>
                {MOCK_RESPONSES[m.id]}
              </div>
            </motion.article>
          ))}
        </motion.div>

        {/* Agreement / Disagreement */}
        <div className="mt-10 grid grid-cols-1 md:grid-cols-2 gap-5">
          <PointList
            title="Agreement Points"
            icon={Check}
            accent="#10B981"
            items={MOCK_SCORES.agreementPoints}
            testId="agreement-list"
          />
          <PointList
            title="Disagreement Points"
            icon={MinusCircle}
            accent="#F43F5E"
            items={MOCK_SCORES.disagreementPoints}
            testId="disagreement-list"
          />
        </div>

        {/* Super Answer */}
        <motion.section
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="relative mt-12 rounded-3xl overflow-hidden border border-[#0066FF]/40"
          data-testid="super-answer-card"
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
                <h2 className="text-2xl md:text-3xl font-semibold tracking-tight text-white">Super Answer</h2>
              </div>
            </div>
            <div className="text-[15.5px] md:text-[16.5px] leading-[1.75] text-white/85 whitespace-pre-line" data-testid="super-answer-body">
              {MOCK_SUPER_ANSWER}
            </div>

            <div className="mt-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-6 border-t border-white/[0.08]">
              <div className="flex flex-wrap items-center gap-3 text-[12px] text-white/50">
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF]" /> Synthesized from 4 models
                </span>
                <span>·</span>
                <span>Consensus {MOCK_SCORES.consensus}%</span>
                <span>·</span>
                <span>Trust {MOCK_SCORES.trust}%</span>
              </div>
              <button
                onClick={() => navigate("/debate")}
                data-testid="see-full-debate-button"
                className="group inline-flex items-center gap-2 rounded-full bg-white text-[#060A14] font-medium px-6 py-3 text-[14px] hover:bg-white/90 transition-colors"
                style={{ boxShadow: "0 20px 50px -18px rgba(0,229,255,0.6)" }}
              >
                <MessagesSquare className="w-4 h-4" />
                See Full Debate
                <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
              </button>
            </div>
          </div>
        </motion.section>
      </main>
    </div>
  );
}

function ScorePill({ icon: Icon, label, value, accent, testId }) {
  return (
    <div
      className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3"
      data-testid={testId}
    >
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center"
        style={{ backgroundColor: `${accent}1a`, border: `1px solid ${accent}33` }}
      >
        <Icon className="w-4 h-4" style={{ color: accent }} />
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">{label}</div>
        <div className="text-lg font-semibold text-white leading-none mt-1">
          {value}
          <span className="text-white/40 text-sm font-normal ml-0.5">%</span>
        </div>
      </div>
    </div>
  );
}

function PointList({ title, icon: Icon, accent, items, testId }) {
  return (
    <div
      className="rounded-2xl border border-white/[0.08] bg-[#0B1120] p-6"
      data-testid={testId}
    >
      <div className="flex items-center gap-2 mb-4">
        <div
          className="w-7 h-7 rounded-md flex items-center justify-center"
          style={{ backgroundColor: `${accent}1a`, border: `1px solid ${accent}33` }}
        >
          <Icon className="w-3.5 h-3.5" style={{ color: accent }} />
        </div>
        <h3 className="text-[15px] font-medium text-white tracking-tight">{title}</h3>
      </div>
      <ul className="space-y-3">
        {items.map((t, i) => (
          <li key={i} className="flex gap-3 text-[14px] leading-relaxed text-white/70">
            <span
              className="mt-2 w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: accent }}
            />
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
