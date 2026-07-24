import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Sparkles } from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { MODELS, MOCK_DEBATE } from "@/lib/mockData";
import { useI18n } from "@/lib/i18n";

export default function Debate() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const isDemo = location.state?.executionMode === "DEMO";
  const modelMap = Object.fromEntries(MODELS.map((m) => [m.id, m]));

  return (
    <div className="relative min-h-screen max-w-full overflow-x-hidden bg-[#060A14] text-white" data-testid="debate-page">
      <div className="pointer-events-none absolute inset-0 grid-pattern opacity-50" />
      <NavBar variant="debate" />

      <main className="relative mx-auto max-w-4xl px-5 md:px-8 pt-10 md:pt-14 pb-32">
        <button
          type="button"
          onClick={() => navigate("/results")}
          data-testid="back-results-button"
          className="inline-flex min-h-11 items-center gap-1.5 rounded-lg text-[13px] text-white/50 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#060A14]"
        >
          <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" /> {t("debate.backResults")}
        </button>

        <div className="mt-6 flex items-start justify-between gap-6 flex-wrap">
          <div>
             <div className="mb-2 text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">{isDemo ? t("debate.demoEyebrow") : t("debate.eyebrow")}</div>
             <h1 className="break-words text-3xl font-semibold tracking-tight [overflow-wrap:anywhere] md:text-4xl">
               {isDemo ? t("debate.demoTitle") : t("debate.liveTitle")}
            </h1>
            <p className="mt-2 text-white/50 text-[14px] max-w-2xl">
              {isDemo
                 ? t("debate.demoDescription")
                 : t("debate.liveDescription")}
            </p>
          </div>
        </div>

        {!isDemo && (
          <div className="mt-10 min-w-0 max-w-full rounded-2xl border border-[#F43F5E]/30 bg-[#F43F5E]/[0.05] p-4 sm:p-6" data-testid="debate-unavailable" role="status">
            <div className="font-medium text-white">{t("debate.unavailableTitle")}</div>
            <p className="mt-2 break-words text-[13.5px] leading-relaxed text-white/55 [overflow-wrap:anywhere]">
              {t("debate.unavailableDescription")}
            </p>
          </div>
        )}

        {/* Demo-only model legend */}
        {isDemo && <div className="mt-8 flex flex-wrap gap-2">
          {MODELS.map((m) => (
            <div
              key={m.id}
              data-testid={`legend-${m.id}`}
              className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[12px]"
            >
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: m.accent }} />
              <span className="break-words text-white/80 [overflow-wrap:anywhere]">{m.label}</span>
              <span className="min-w-0 break-words text-white/40 [overflow-wrap:anywhere]">· {m.codename}</span>
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
                className={"flex min-w-0 max-w-full gap-2 sm:gap-3 " + (align === "right" ? "flex-row-reverse" : "")}
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
                <div className={"min-w-0 max-w-[calc(100%-2.75rem)] sm:max-w-[78%] " + (align === "right" ? "items-end text-right" : "")}>
                  <div className={"mb-1 break-words text-[11px] text-white/40 [overflow-wrap:anywhere] " + (align === "right" ? "text-right" : "")}>
                    {m.codename} <span className="text-white/25">· {m.provider}</span>
                  </div>
                  <div
                    className="relative min-w-0 max-w-full break-words rounded-2xl px-4 py-3 text-[14.5px] leading-relaxed text-white/85 [overflow-wrap:anywhere] sm:px-5 sm:py-4"
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
          className="mt-12 flex min-w-0 max-w-full flex-col items-start gap-4 rounded-2xl border border-[#00E5FF]/30 bg-[#00E5FF]/[0.04] p-4 sm:flex-row sm:items-center sm:p-6"
          data-testid="debate-verdict"
        >
          <div className="w-10 h-10 rounded-xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-[#00E5FF]" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80">{t("debate.consensusReached")}</div>
            <div className="mt-0.5 break-words text-[15px] text-white [overflow-wrap:anywhere]">
              {t("debate.demoVerdictDescription")}
            </div>
          </div>
          <button
            type="button"
            onClick={() => navigate("/results")}
            data-testid="return-verdict-button"
            className="min-h-11 w-full rounded-full bg-white px-5 py-2.5 text-[13px] font-medium text-[#060A14] transition-colors hover:bg-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B1120] sm:w-auto"
          >
            {t("debate.viewConclusion")}
          </button>
        </motion.div>}
      </main>
    </div>
  );
}
