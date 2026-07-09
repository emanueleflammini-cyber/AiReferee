import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import {
  Recycle,
  Sparkles,
  ArrowLeft,
  ArrowRight,
  Clock,
  ShieldCheck,
  Gauge,
  Trophy,
  AlertTriangle,
} from "lucide-react";
import { NavBar } from "@/components/NavBar";

const TOPIC_LABEL = {
  stable: "Stable knowledge · reusable 30 days",
  technical: "Technical explanation · reusable 14 days",
  sensitive: "Sensitive topic · always refreshed",
  news: "News / current event · never cached",
};

export default function ReuseFound() {
  const navigate = useNavigate();
  const loc = useLocation();
  const state = loc.state || {};
  const match = state.match;
  const topic = state.topic || "stable";
  const queryId = state.queryId || null;

  if (!match) {
    navigate("/", { replace: true });
    return null;
  }

  const useExisting = () => {
    toast.success("Reused a prior consensus", { description: `${match.similarity}% match · ${match.age_days}d old` });
    navigate("/results", {
      state: { mode: "reused", queryId, match, topic },
      replace: true,
    });
  };

  const refresh = () => {
    navigate("/results", {
      state: { mode: "updated", queryId, replacedMatch: match, topic },
      replace: true,
    });
  };

  return (
    <div className="relative min-h-screen bg-[#060A14] text-white overflow-hidden" data-testid="reuse-found-page">
      <div className="pointer-events-none absolute inset-0 opacity-60 grid-pattern" />
      <div className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full blur-3xl opacity-25"
        style={{ background: "radial-gradient(circle, rgba(0,229,255,0.25), transparent 70%)" }}
      />
      <NavBar variant="reuse" />

      <main className="relative mx-auto max-w-3xl px-5 md:px-8 pt-10 md:pt-14 pb-24">
        <button
          onClick={() => navigate("/")}
          data-testid="reuse-back"
          className="inline-flex items-center gap-1.5 text-[13px] text-white/50 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to prompt
        </button>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="mt-6"
        >
          <div className="inline-flex items-center gap-2 rounded-full border border-[#00E5FF]/40 bg-[#00E5FF]/[0.08] px-3.5 py-1.5 text-[12px] text-[#00E5FF] mb-5">
            <Recycle className="w-3.5 h-3.5" />
            Smart Reuse — reusable consensus found
          </div>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight leading-tight" data-testid="reuse-title">
            You've asked something similar before.
          </h1>
          <p className="mt-3 text-[15px] text-white/60 max-w-2xl leading-relaxed">
            Referee found a prior Trusted Conclusion that overlaps with your question. Reuse it for an instant answer, or run a fresh multi-model comparison to update it.
          </p>
        </motion.div>

        {/* Match card */}
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.1 }}
          className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0B1120]/80 backdrop-blur-xl p-6 md:p-8"
          data-testid="match-card"
        >
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex-1 min-w-0">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/40 mb-2">Previous question</div>
              <div className="text-lg md:text-xl text-white leading-snug tracking-tight" data-testid="match-prompt">
                “{match.prompt}”
              </div>
            </div>
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-[#00E5FF]/40 bg-[#00E5FF]/[0.08] px-3 py-1 text-[11.5px] font-mono text-[#00E5FF] flex-shrink-0"
              data-testid="match-similarity"
            >
              <Sparkles className="w-3 h-3" />
              {match.similarity}% match
            </span>
          </div>

          {/* Meta strip */}
          <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetaTile icon={Clock} label="Age" value={`${match.age_days}d old`} testId="match-age" />
            <MetaTile icon={Gauge} label="Confidence" value={`${match.confidence}%`} testId="match-confidence" />
            <MetaTile icon={Trophy} label="Consensus" value={`${match.consensus}%`} testId="match-consensus" />
            <MetaTile icon={ShieldCheck} label="Trust" value={`${match.trust}%`} testId="match-trust" />
          </div>

          <div className="mt-6 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 flex items-start gap-3">
            <div className="w-7 h-7 rounded-md bg-[#00E5FF]/10 border border-[#00E5FF]/25 flex items-center justify-center flex-shrink-0">
              <Recycle className="w-3.5 h-3.5 text-[#00E5FF]" />
            </div>
            <div className="text-[13px] text-white/70 leading-relaxed" data-testid="match-topic">
              {TOPIC_LABEL[topic] || TOPIC_LABEL.stable}
            </div>
          </div>

          {/* Actions */}
          <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              onClick={useExisting}
              data-testid="reuse-use-existing"
              className="group inline-flex items-center justify-center gap-2 rounded-2xl bg-white text-[#060A14] font-medium px-5 py-3.5 text-[14px] hover:bg-white/90 transition-colors"
              style={{ boxShadow: "0 20px 50px -18px rgba(0,229,255,0.6)" }}
            >
              <Recycle className="w-4 h-4" />
              Use existing Trusted Conclusion
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </button>
            <button
              onClick={refresh}
              data-testid="reuse-refresh"
              className="inline-flex items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] text-white font-medium px-5 py-3.5 text-[14px] transition-colors"
            >
              <Sparkles className="w-4 h-4 text-[#00E5FF]" />
              Refresh with new AI comparison
            </button>
          </div>

          <div className="mt-5 flex items-start gap-2 text-[12px] text-white/45">
            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>Reused conclusions cite the original model responses. Refreshing charges a full multi-model comparison and overwrites the cache.</span>
          </div>
        </motion.section>
      </main>
    </div>
  );
}

function MetaTile({ icon: Icon, label, value, testId }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 flex items-center gap-2.5" data-testid={testId}>
      <div className="w-7 h-7 rounded-md bg-white/[0.03] border border-white/10 flex items-center justify-center">
        <Icon className="w-3.5 h-3.5 text-white/70" />
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-[0.22em] text-white/40">{label}</div>
        <div className="text-[14px] text-white font-medium leading-tight mt-0.5">{value}</div>
      </div>
    </div>
  );
}
