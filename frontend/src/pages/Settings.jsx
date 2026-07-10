import { useNavigate, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import {
  ArrowLeft,
  Recycle,
  Sparkles,
  ShieldAlert,
  Zap,
  Check,
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { useQueryState } from "@/lib/QueryContext";
import { useI18n } from "@/lib/i18n";

const OPTION_META = [
  { id: "ask", icon: Recycle, accent: "#00E5FF", labelKey: "settings.prefAsk", hintKey: "settings.prefAskHint" },
  { id: "prefer_fresh", icon: Sparkles, accent: "#0066FF", labelKey: "settings.prefFresh", hintKey: "settings.prefFreshHint" },
  { id: "prefer_reused", icon: Zap, accent: "#10B981", labelKey: "settings.prefReused", hintKey: "settings.prefReusedHint" },
  { id: "never_sensitive", icon: ShieldAlert, accent: "#F59E0B", labelKey: "settings.prefSensitive", hintKey: "settings.prefSensitiveHint" },
];

export default function Settings() {
  const navigate = useNavigate();
  const loc = useLocation();
  const { settings, setSettings } = useQueryState();
  const { t } = useI18n();

  const back = () => {
    if (loc.state?.from) navigate(loc.state.from);
    else navigate("/");
  };

  const setPref = (id) => {
    setSettings({ reusePref: id });
    toast.success("Preference updated");
  };

  return (
    <div className="relative min-h-screen bg-[#060A14] text-white overflow-hidden" data-testid="settings-page">
      <div className="pointer-events-none absolute inset-0 opacity-60 grid-pattern" />
      <NavBar variant="settings" />

      <main className="relative mx-auto max-w-3xl px-5 md:px-8 pt-10 md:pt-14 pb-24">
        <button
          onClick={back}
          data-testid="settings-back"
          className="inline-flex items-center gap-1.5 text-[13px] text-white/50 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> {t("nav.back")}
        </button>

        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="mt-6">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-2">{t("settings.eyebrow")}</div>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight">{t("settings.title")}</h1>
        </motion.div>

        <section className="mt-10" data-testid="smart-reuse-preferences">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-white/45 mb-4">
            <Recycle className="w-3.5 h-3.5" /> {t("settings.reusePrefs")}
          </div>
          <p className="text-[13.5px] text-white/55 leading-relaxed max-w-2xl -mt-2 mb-6">
            {t("settings.reuseHint")}
          </p>

          <div className="space-y-3">
            {OPTION_META.map((o) => {
              const active = settings.reusePref === o.id;
              const Icon = o.icon;
              return (
                <button
                  key={o.id}
                  onClick={() => setPref(o.id)}
                  data-testid={`pref-${o.id}`}
                  className={
                    "w-full text-left rounded-2xl border p-5 transition-colors flex items-start gap-4 " +
                    (active
                      ? "border-[#00E5FF]/50 bg-[#00E5FF]/[0.05]"
                      : "border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.04] hover:border-white/20")
                  }
                >
                  <div
                    className="w-10 h-10 rounded-xl border flex-shrink-0 flex items-center justify-center"
                    style={{
                      backgroundColor: `${o.accent}18`,
                      borderColor: `${o.accent}55`,
                    }}
                  >
                    <Icon className="w-4 h-4" style={{ color: o.accent }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[15px] font-medium text-white tracking-tight">{t(o.labelKey)}</div>
                      {active && (
                        <span className="inline-flex items-center gap-1 text-[11px] text-[#00E5FF]" data-testid={`pref-${o.id}-active`}>
                          <Check className="w-3.5 h-3.5" /> {t("common.active")}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-[13px] text-white/55 leading-relaxed">{t(o.hintKey)}</div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Policy reference */}
          <div className="mt-8 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="reuse-policy-summary">
            <div className="text-[11px] uppercase tracking-[0.22em] text-white/45 mb-3">{t("settings.policy")}</div>
            <ul className="grid grid-cols-1 md:grid-cols-2 gap-y-2 gap-x-6 text-[13px] text-white/70">
              <li className="flex justify-between gap-3"><span>{t("settings.stable")}</span><span className="text-white/50 font-mono">{t("settings.policyStable")}</span></li>
              <li className="flex justify-between gap-3"><span>{t("settings.technical")}</span><span className="text-white/50 font-mono">{t("settings.policyTechnical")}</span></li>
              <li className="flex justify-between gap-3"><span>{t("settings.sensitive")}</span><span className="text-white/50 font-mono">{t("settings.policySensitive")}</span></li>
              <li className="flex justify-between gap-3"><span>{t("settings.news")}</span><span className="text-white/50 font-mono">{t("settings.policyNews")}</span></li>
            </ul>
          </div>
        </section>
      </main>
    </div>
  );
}
