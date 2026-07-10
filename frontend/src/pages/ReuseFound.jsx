import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import axios from "axios";
import {
  Recycle, Sparkles, ArrowLeft, ArrowRight, Clock, ShieldCheck,
  Gauge, Trophy, AlertTriangle, Languages, Coins, Timer, Zap,
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { useI18n } from "@/lib/i18n";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function ReuseFound() {
  const navigate = useNavigate();
  const loc = useLocation();
  const { t, lang } = useI18n();
  const state = loc.state || {};
  const match = state.match;
  const topic = state.topic || "stable";
  const queryId = state.queryId || null;
  const savings = state.savings || null;
  const answerLang = state.answerLanguage || lang;
  const originalLang = match?.original_language || "en";
  const needsTranslation = match?.needs_translation === true || originalLang !== answerLang;

  if (!match) {
    navigate("/", { replace: true });
    return null;
  }

  const useExisting = async () => {
    let translation = null;
    if (needsTranslation) {
      try {
        const r = await axios.post(`${API}/conclusions/${match.id}/translate`, { target_language: answerLang });
        translation = r.data;
      } catch (e) {
        console.warn("Translate failed", e);
      }
    }
    toast.success(t("reuse.found"), { description: `${match.similarity}% ${t("reuse.match")} · ${match.age_days}${t("reuse.days")}` });
    navigate("/results", {
      state: {
        mode: "reused", queryId, match, topic,
        answerLanguage: answerLang, savings,
        translation,          // {text, cache_hit, cost_usd, input_tokens, output_tokens}
      },
      replace: true,
    });
  };

  const refresh = () => {
    navigate("/results", {
      state: { mode: "updated", queryId, replacedMatch: match, topic, answerLanguage: answerLang, savings },
      replace: true,
    });
  };

  const cost = savings?.cost_saved_usd || 0;
  const timeSec = ((savings?.response_time_saved_ms || 0) / 1000).toFixed(1);

  return (
    <div className="relative min-h-screen bg-[#060A14] text-white overflow-hidden" data-testid="reuse-found-page">
      <div className="pointer-events-none absolute inset-0 opacity-60 grid-pattern" />
      <div className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full blur-3xl opacity-25"
        style={{ background: "radial-gradient(circle, rgba(0,229,255,0.25), transparent 70%)" }} />
      <NavBar variant="reuse" />

      <main className="relative mx-auto max-w-3xl px-5 md:px-8 pt-10 md:pt-14 pb-24">
        <button
          onClick={() => navigate("/")}
          data-testid="reuse-back"
          className="inline-flex items-center gap-1.5 text-[13px] text-white/50 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> {t("nav.back")}
        </button>

        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }} className="mt-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#00E5FF]/40 bg-[#00E5FF]/[0.08] px-3.5 py-1.5 text-[12px] text-[#00E5FF] mb-5" data-testid="reuse-badge">
            <Recycle className="w-3.5 h-3.5" />
            {t("reuse.found")}
          </div>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight leading-tight" data-testid="reuse-title">
            {t("reuse.title")}
          </h1>
          <p className="mt-3 text-[15px] text-white/60 max-w-2xl leading-relaxed">{t("reuse.subtitle")}</p>
        </motion.div>

        <motion.section
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.1 }}
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
              {match.similarity}% {t("reuse.match")}
            </span>
          </div>

          {/* Language pair + subtle translation notice */}
          <div className="mt-4 flex items-center gap-2 flex-wrap text-[12.5px]" data-testid="lang-pair">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-0.5 text-white/70">
              <span className="uppercase font-mono text-white/60">{originalLang}</span>
              <span className="text-white/40">{t("reuse.originalLang")}</span>
            </span>
            <ArrowRight className="w-3 h-3 text-white/30" />
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-0.5 text-white/70">
              <span className="uppercase font-mono text-white/60">{answerLang}</span>
              <span className="text-white/40">{t("reuse.answerLang")}</span>
            </span>
            {needsTranslation && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full border border-[#A78BFA]/40 bg-[#A78BFA]/[0.06] px-2.5 py-0.5 text-[11.5px] text-[#A78BFA]"
                data-testid="global-match-badge"
              >
                <Languages className="w-3 h-3" />
                {t("reuse.globalMatch", { source: originalLang.toUpperCase(), target: answerLang.toUpperCase() })}
              </span>
            )}
          </div>

          <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetaTile icon={Clock} label={t("reuse.age")} value={`${match.age_days}${t("reuse.days")}`} testId="match-age" />
            <MetaTile icon={Gauge} label={t("reuse.confidence")} value={`${match.confidence}%`} testId="match-confidence" />
            <MetaTile icon={Trophy} label={t("reuse.consensus")} value={`${match.consensus}%`} testId="match-consensus" />
            <MetaTile icon={ShieldCheck} label={t("reuse.trust")} value={`${match.trust}%`} testId="match-trust" />
          </div>

          {/* Savings strip */}
          {savings && (
            <div className="mt-6 grid grid-cols-3 gap-3" data-testid="savings-strip">
              <MetaTile icon={Zap} accent="#10B981" label={t("reuse.apiCallsAvoided")} value={savings.api_calls_avoided} testId="save-calls" />
              <MetaTile icon={Coins} accent="#00E5FF" label={t("reuse.costSaved")} value={`~$${cost.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`} testId="save-cost" />
              <MetaTile icon={Timer} accent="#F59E0B" label={t("reuse.timeSaved")} value={`~${timeSec}${t("reuse.seconds")}`} testId="save-time" />
            </div>
          )}

          <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              onClick={useExisting}
              data-testid="reuse-use-existing"
              className="group inline-flex items-center justify-center gap-2 rounded-2xl bg-white text-[#060A14] font-medium px-5 py-3.5 text-[14px] hover:bg-white/90 transition-colors"
              style={{ boxShadow: "0 20px 50px -18px rgba(0,229,255,0.6)" }}
            >
              <Recycle className="w-4 h-4" />
              {t("reuse.useExisting")}
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </button>
            <button
              onClick={refresh}
              data-testid="reuse-refresh"
              className="inline-flex items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] text-white font-medium px-5 py-3.5 text-[14px] transition-colors"
            >
              <Sparkles className="w-4 h-4 text-[#00E5FF]" />
              {t("reuse.refresh")}
            </button>
          </div>

          <div className="mt-5 flex items-start gap-2 text-[12px] text-white/45">
            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>{t("reuse.caveat")}</span>
          </div>
        </motion.section>
      </main>
    </div>
  );
}

function MetaTile({ icon: Icon, label, value, testId, accent = "#ffffff40" }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 flex items-center gap-2.5" data-testid={testId}>
      <div className="w-7 h-7 rounded-md bg-white/[0.03] border border-white/10 flex items-center justify-center">
        <Icon className="w-3.5 h-3.5" style={{ color: accent }} />
      </div>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-[0.22em] text-white/40 truncate">{label}</div>
        <div className="text-[14px] text-white font-medium leading-tight mt-0.5 truncate">{value}</div>
      </div>
    </div>
  );
}
