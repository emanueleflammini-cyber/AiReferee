import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Sparkles } from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { MODELS, MOCK_DEBATE } from "@/lib/mockData";

export default function Debate() {
  const navigate = useNavigate();
  const location = useLocation();
  const isDemo = location.state?.executionMode === "DEMO";
  const modelMap = Object.fromEntries(MODELS.map((m) => [m.id, m]));

  return (
    <div className="relative min-h-screen bg-[#060A14] text-white overflow-hidden" data-testid="debate-page">
      <div className="pointer-events-none absolute inset-0 grid-pattern opacity-50" />
      <NavBar variant="debate" />

      <main className="relative mx-auto max-w-4xl px-5 md:px-8 pt-10 md:pt-14 pb-32">
        <button
          onClick={() => navigate("/results")}
          data-testid="back-results-button"
          className="inline-flex items-center gap-1.5 text-[13px] text-white/50 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to results
        </button>

        <div className="mt-6 flex items-start justify-between gap-6 flex-wrap">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-2">{isDemo ? "Demo Debate" : "Debate"}</div>
            <h1 className="text-3xl md:text-4xl font-semibold tracking-tight">
              {isDemo ? "How the referee reached consensus" : "No verified transcript is available"}
            </h1>
            <p className="mt-2 text-white/50 text-[14px] max-w-2xl">
              {isDemo
                ? "A simulated transcript used only to demonstrate the debate experience."
                : "LIVE execution shows only data returned by the providers."}
            </p>
          </div>
        </div>

        {!isDemo && (
          <div className="mt-10 rounded-2xl border border-[#F43F5E]/30 bg-[#F43F5E]/[0.05] p-6" data-testid="debate-unavailable">
            <div className="font-medium text-white">Live debate transcript unavailable</div>
            <p className="mt-2 text-[13.5px] leading-relaxed text-white/55">
              AI Referee does not fabricate a debate transcript during LIVE execution.
            </p>
          </div>
        )}

        {/* Demo-only model legend */}
        {isDemo && <div className="mt-8 flex flex-wrap gap-2">
          {MODELS.map((m) => (
            <div
              key={m.id}
              data-testid={`legend-${m.id}`}
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[12px]"
            >
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: m.accent }} />
              <span className="text-white/80">{m.label}</span>
              <span className="text-white/40">· {m.codename}</span>
            </div>
          ))}
        </div>}

        {/* Chat */}
        {isDemo && <div className="mt-10 space-y-5" data-testid="debate-thread">
          {MOCK_DEBATE.map((msg, i) => {
            const m = modelMap[msg.model];
            const align = i % 2 === 0 ? "left" : "right";
            return (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 14 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.45, delay: Math.min(i * 0.03, 0.3) }}
                className={"flex gap-3 " + (align === "right" ? "flex-row-reverse" : "")}
              >
                <div
                  className="w-9 h-9 rounded-full border flex items-center justify-center flex-shrink-0 mt-1 font-medium text-[12px]"
                  style={{
                    backgroundColor: `${m.accent}1a`,
                    borderColor: `${m.accent}55`,
                    color: m.accent,
                  }}
                  data-testid={`avatar-${msg.model}-${i}`}
                >
                  {m.label.replace("Model ", "")}
                </div>
                <div className={"max-w-[78%] " + (align === "right" ? "items-end text-right" : "")}>
                  <div className={"text-[11px] text-white/40 mb-1 " + (align === "right" ? "text-right" : "")}>
                    {m.codename} <span className="text-white/25">· {m.provider}</span>
                  </div>
                  <div
                    className="relative rounded-2xl px-5 py-4 text-[14.5px] leading-relaxed text-white/85"
                    style={{
                      background: `linear-gradient(180deg, ${m.accent}0f, transparent), #0B1120`,
                      border: `1px solid ${m.accent}22`,
                    }}
                  >
                    {msg.text}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>}

        {/* Verdict footer */}
        {isDemo && <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="mt-12 rounded-2xl border border-[#00E5FF]/30 bg-[#00E5FF]/[0.04] p-6 flex items-center gap-4"
          data-testid="debate-verdict"
        >
          <div className="w-10 h-10 rounded-xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-[#00E5FF]" />
          </div>
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">Consensus reached</div>
            <div className="text-white text-[15px] mt-0.5">
              All four models aligned on the three-axis framing. Super Answer ready.
            </div>
          </div>
          <button
            onClick={() => navigate("/results")}
            data-testid="return-verdict-button"
            className="rounded-full bg-white text-[#060A14] px-5 py-2.5 text-[13px] font-medium hover:bg-white/90 transition-colors"
          >
            View Super Answer
          </button>
        </motion.div>}
      </main>
    </div>
  );
}
