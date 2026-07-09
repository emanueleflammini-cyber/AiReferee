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

const OPTIONS = [
  {
    id: "ask",
    label: "Always ask before reusing",
    hint: "Referee will show the Reusable Consensus screen every time a match is found.",
    icon: Recycle,
    accent: "#00E5FF",
  },
  {
    id: "prefer_fresh",
    label: "Prefer fresh results",
    hint: "Skip the reuse prompt and run a new multi-model comparison by default.",
    icon: Sparkles,
    accent: "#0066FF",
  },
  {
    id: "prefer_reused",
    label: "Prefer faster reused results",
    hint: "Automatically reuse a matching prior conclusion when one exists within the cache window.",
    icon: Zap,
    accent: "#10B981",
  },
  {
    id: "never_sensitive",
    label: "Never reuse sensitive topics",
    hint: "Always run fresh comparisons for financial, legal, medical and current-event topics. Other topics may still be reused.",
    icon: ShieldAlert,
    accent: "#F59E0B",
  },
];

export default function Settings() {
  const navigate = useNavigate();
  const loc = useLocation();
  const { settings, setSettings } = useQueryState();

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
          <ArrowLeft className="w-3.5 h-3.5" /> Back
        </button>

        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="mt-6">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-2">Settings</div>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight">Preferences</h1>
        </motion.div>

        <section className="mt-10" data-testid="smart-reuse-preferences">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-white/45 mb-4">
            <Recycle className="w-3.5 h-3.5" /> Smart Reuse Preferences
          </div>
          <p className="text-[13.5px] text-white/55 leading-relaxed max-w-2xl -mt-2 mb-6">
            Referee caches prior Trusted Conclusions and offers to reuse them when you ask a similar question. Choose how aggressively it should reuse.
          </p>

          <div className="space-y-3">
            {OPTIONS.map((o) => {
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
                      <div className="text-[15px] font-medium text-white tracking-tight">{o.label}</div>
                      {active && (
                        <span className="inline-flex items-center gap-1 text-[11px] text-[#00E5FF]" data-testid={`pref-${o.id}-active`}>
                          <Check className="w-3.5 h-3.5" /> Selected
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-[13px] text-white/55 leading-relaxed">{o.hint}</div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Policy reference */}
          <div className="mt-8 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="reuse-policy-summary">
            <div className="text-[11px] uppercase tracking-[0.22em] text-white/45 mb-3">Cache policy</div>
            <ul className="grid grid-cols-1 md:grid-cols-2 gap-y-2 gap-x-6 text-[13px] text-white/70">
              <li className="flex justify-between gap-3"><span>Stable knowledge</span><span className="text-white/50 font-mono">reusable · 30 days</span></li>
              <li className="flex justify-between gap-3"><span>Technical explanations</span><span className="text-white/50 font-mono">reusable · 14 days</span></li>
              <li className="flex justify-between gap-3"><span>Financial / legal / medical</span><span className="text-white/50 font-mono">always refresh</span></li>
              <li className="flex justify-between gap-3"><span>News / prices / weather</span><span className="text-white/50 font-mono">never reuse</span></li>
            </ul>
          </div>
        </section>
      </main>
    </div>
  );
}
