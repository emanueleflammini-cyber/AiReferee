import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import axios from "axios";
import { toast } from "sonner";
import {
  Sparkles,
  Gauge,
  Layers,
  Users,
  LayoutList,
  ArrowRight,
  ShieldCheck,
  Zap,
  Brain,
  ChevronRight,
  Target,
  Scale,
  Lightbulb,
  Search,
  Rocket,
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { Slider } from "@/components/ui/slider";
import { useQueryState } from "@/lib/QueryContext";
import { STRATEGIES, SUPPORTED_MODELS, WORKFLOW_STEPS } from "@/lib/mockData";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const AUDIENCES = [
  { id: "beginner", label: "Beginner" },
  { id: "professional", label: "Professional" },
  { id: "expert", label: "Expert" },
];

const FORMATS = [
  { id: "paragraph", label: "Paragraph" },
  { id: "bullets", label: "Bullet List" },
  { id: "table", label: "Table" },
  { id: "steps", label: "Step-by-step" },
];

const STRATEGY_ICONS = {
  max_accuracy: Target,
  balanced: Scale,
  creative: Lightbulb,
  critical: Search,
  fast: Rocket,
};

export default function Home() {
  const navigate = useNavigate();
  const { query, setQuery, settings } = useQueryState();
  const [submitting, setSubmitting] = useState(false);
  const taRef = useRef(null);

  const autosize = () => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 360) + "px";
  };

  useEffect(() => { autosize(); }, [query.prompt]);

  const handleGenerate = async () => {
    if (!query.prompt.trim()) {
      toast.error("Ask something first — the referee can't judge silence.");
      taRef.current?.focus();
      return;
    }
    setSubmitting(true);
    const payload = {
      prompt: query.prompt,
      goal: query.goal,
      detail: query.detail,
      audience: query.audience,
      format: query.format,
      strategy: query.strategy,
    };
    // 1) persist the query and grab its id
    let queryId = null;
    try {
      const r = await axios.post(`${API}/queries`, payload);
      queryId = r.data?.id || null;
    } catch (e) {
      console.warn("Query save failed", e);
    }

    // 2) Smart Reuse — ask the server whether a prior conclusion can be reused
    let matchRes = null;
    try {
      const r = await axios.post(`${API}/queries/match`, { prompt: query.prompt });
      matchRes = r.data;
    } catch (e) {
      console.warn("Match check failed", e);
    }
    setSubmitting(false);

    const pref = settings?.reusePref || "ask";

    if (!matchRes || matchRes.policy === "never_reuse") {
      navigate("/results", { state: { mode: "fresh", queryId, policy: matchRes?.policy, topic: matchRes?.topic, reason: matchRes?.reason } });
      return;
    }
    if (matchRes.policy === "always_refresh") {
      navigate("/results", { state: { mode: "fresh", queryId, policy: matchRes.policy, topic: matchRes.topic, reason: matchRes.reason } });
      return;
    }
    if (!matchRes.match) {
      navigate("/results", { state: { mode: "fresh", queryId, topic: matchRes.topic } });
      return;
    }
    if (pref === "never_sensitive" && (matchRes.topic === "sensitive" || matchRes.topic === "news")) {
      navigate("/results", { state: { mode: "fresh", queryId, topic: matchRes.topic } });
      return;
    }
    if (pref === "prefer_reused") {
      navigate("/results", { state: { mode: "reused", queryId, match: matchRes.match, topic: matchRes.topic } });
      return;
    }
    if (pref === "prefer_fresh") {
      navigate("/results", { state: { mode: "updated", queryId, replacedMatch: matchRes.match, topic: matchRes.topic } });
      return;
    }
    navigate("/reuse-found", { state: { queryId, match: matchRes.match, topic: matchRes.topic } });
  };

  const goalLabel =
    query.goal < 33 ? "Leaning Accuracy" :
    query.goal > 66 ? "Leaning Creativity" : "Balanced";
  const detailLabel =
    query.detail < 33 ? "Quick take" :
    query.detail > 66 ? "Deep dive" : "Balanced";

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#060A14] text-white" data-testid="home-page">
      <div className="pointer-events-none absolute inset-0 hero-glow" />
      <div className="pointer-events-none absolute inset-0 grid-pattern opacity-70" />
      <div className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full blur-3xl opacity-30 animate-float-slow"
        style={{ background: "radial-gradient(circle, rgba(0,102,255,0.25), transparent 70%)" }}
      />

      <NavBar />

      <main className="relative mx-auto max-w-5xl px-5 md:px-8 pt-16 md:pt-24 pb-24">
        {/* Hero */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="text-center"
        >
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] backdrop-blur-md px-3.5 py-1.5 text-[12px] text-white/70 mb-8"
            data-testid="hero-badge"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#00E5FF] animate-pulse-ring" />
            The first AI Consensus Platform
          </div>
          <h1
            className="text-5xl sm:text-6xl md:text-7xl font-semibold tracking-tighter leading-[1.02]"
            data-testid="hero-title"
          >
            AI <span className="shimmer-text">Referee</span>
          </h1>
          <p className="mt-6 text-lg md:text-xl text-white/70 max-w-2xl mx-auto leading-relaxed" data-testid="hero-subtitle">
            <span className="text-white">One Question.</span>{" "}
            <span className="text-white/80">Multiple AI Minds.</span>{" "}
            <span className="text-white">One Trusted Conclusion.</span>
          </p>
          <p className="mt-5 text-[15px] text-white/55 max-w-2xl mx-auto leading-relaxed" data-testid="hero-pitch">
            The first AI Consensus Platform that combines the best reasoning from multiple AI models into one transparent answer.
          </p>
        </motion.div>

        {/* Ask box */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.15, ease: "easeOut" }}
          className="relative mt-14"
        >
          <div className="relative rounded-3xl border border-white/10 bg-[#0B1120]/80 backdrop-blur-xl overflow-hidden focus-within:border-[#00E5FF]/40 transition-colors"
            style={{ boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), 0 30px 80px -20px rgba(0,102,255,0.35)" }}
          >
            <div className="p-6 md:p-8">
              <textarea
                ref={taRef}
                data-testid="ask-textarea"
                className="ask-textarea text-xl md:text-2xl leading-relaxed min-h-[80px] tracking-tight"
                placeholder="Ask anything..."
                value={query.prompt}
                onChange={(e) => setQuery({ ...query, prompt: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleGenerate();
                }}
              />
            </div>

            <div className="border-t border-white/[0.06] bg-[#080D18]/40 px-6 md:px-8 py-6 space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <SliderField
                  icon={Gauge}
                  label="Response Goal"
                  leftLabel="Accuracy"
                  rightLabel="Creativity"
                  value={query.goal}
                  onChange={(v) => setQuery({ ...query, goal: v })}
                  hint={goalLabel}
                  testId="slider-goal"
                />
                <SliderField
                  icon={Layers}
                  label="Detail Level"
                  leftLabel="Quick"
                  rightLabel="Deep"
                  value={query.detail}
                  onChange={(v) => setQuery({ ...query, detail: v })}
                  hint={detailLabel}
                  testId="slider-detail"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] items-center gap-4">
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-white/45">
                  <Users className="w-3.5 h-3.5" /> Audience
                </div>
                <div className="flex flex-wrap gap-2" data-testid="audience-group">
                  {AUDIENCES.map((a) => {
                    const active = query.audience === a.id;
                    return (
                      <button
                        key={a.id}
                        onClick={() => setQuery({ ...query, audience: a.id })}
                        data-testid={`audience-${a.id}`}
                        className={
                          "rounded-full px-4 py-1.5 text-[13px] transition-colors border " +
                          (active
                            ? "bg-white text-[#060A14] border-white shadow-[0_0_20px_rgba(0,229,255,0.35)]"
                            : "bg-white/[0.03] border-white/10 text-white/70 hover:text-white hover:bg-white/[0.06]")
                        }
                      >
                        {a.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] items-center gap-4">
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-white/45">
                  <LayoutList className="w-3.5 h-3.5" /> Format
                </div>
                <div className="flex flex-wrap gap-2" data-testid="format-group">
                  {FORMATS.map((f) => {
                    const active = query.format === f.id;
                    return (
                      <button
                        key={f.id}
                        onClick={() => setQuery({ ...query, format: f.id })}
                        data-testid={`format-${f.id}`}
                        className={
                          "rounded-full px-4 py-1.5 text-[13px] transition-colors border " +
                          (active
                            ? "bg-[#00E5FF]/10 text-[#00E5FF] border-[#00E5FF]/40"
                            : "bg-white/[0.03] border-white/10 text-white/70 hover:text-white hover:bg-white/[0.06]")
                        }
                      >
                        {f.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* Conclusion Strategy */}
          <div className="mt-8" data-testid="strategy-section">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-white/45 mb-3">
              <Sparkles className="w-3.5 h-3.5 text-[#00E5FF]" /> Conclusion Strategy
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5" data-testid="strategy-group">
              {STRATEGIES.map((s) => {
                const active = query.strategy === s.id;
                const Icon = STRATEGY_ICONS[s.id] || Sparkles;
                return (
                  <button
                    key={s.id}
                    onClick={() => setQuery({ ...query, strategy: s.id })}
                    data-testid={`strategy-${s.id}`}
                    className={
                      "text-left rounded-2xl border p-3.5 transition-colors " +
                      (active
                        ? "border-[#00E5FF]/60 bg-[#00E5FF]/[0.06]"
                        : "border-white/10 bg-white/[0.02] hover:bg-white/[0.04] hover:border-white/20")
                    }
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <Icon className={"w-3.5 h-3.5 " + (active ? "text-[#00E5FF]" : "text-white/60")} />
                      <span className={"text-[13px] font-medium " + (active ? "text-white" : "text-white/85")}>{s.label}</span>
                    </div>
                    <div className="text-[11.5px] leading-snug text-white/45">{s.hint}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="text-[12px] text-white/45 hidden sm:block">Press ⌘/Ctrl + Enter to submit</div>
            <button
              onClick={handleGenerate}
              disabled={submitting}
              data-testid="generate-conclusion-button"
              className="group inline-flex items-center gap-2.5 rounded-full bg-[#0066FF] hover:bg-[#0052CC] text-white font-medium px-7 py-3.5 text-[15px] transition-colors disabled:opacity-70"
              style={{ boxShadow: "0 0 0 1px rgba(255,255,255,0.08) inset, 0 20px 40px -12px rgba(0,102,255,0.6)" }}
            >
              <Sparkles className="w-4 h-4 transition-transform group-hover:rotate-12" />
              {submitting ? "Summoning models..." : "Generate Conclusion"}
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </button>
          </div>
        </motion.div>

        {/* How it works */}
        <section id="how" className="mt-28" data-testid="how-it-works">
          <SectionHeader
            eyebrow="How it works"
            title="From your question to a conclusion you can trust"
            body="Every step is transparent — you always see what the models agreed on, disagreed on, and why."
          />
          <div className="mt-10 overflow-x-auto pb-3 -mx-5 px-5">
            <div className="flex items-stretch gap-3 md:grid md:grid-cols-7 md:gap-3 min-w-max md:min-w-0">
              {WORKFLOW_STEPS.map((s, i) => (
                <div key={s.id} className="flex items-stretch gap-3 md:contents">
                  <WorkflowStep index={i + 1} title={s.title} body={s.body} isLast={i === WORKFLOW_STEPS.length - 1} />
                  {i < WORKFLOW_STEPS.length - 1 && (
                    <div className="hidden md:flex items-center justify-center text-white/25">
                      <ChevronRight className="w-4 h-4" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Supported Models */}
        <section id="models" className="mt-28" data-testid="supported-models-section">
          <SectionHeader
            eyebrow="Supported Models"
            title="The world's leading AI minds, in one room"
            body="Referee sends your question to each in parallel — and only surfaces what they can agree on."
          />
          <div className="mt-10 grid grid-cols-2 md:grid-cols-3 gap-3">
            {SUPPORTED_MODELS.map((m) => (
              <div
                key={m.id}
                data-testid={`model-chip-${m.id}`}
                className="group rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5 hover:bg-white/[0.04] hover:border-white/20 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-xl border flex items-center justify-center font-medium text-[13px]"
                    style={{
                      backgroundColor: `${m.accent}18`,
                      borderColor: `${m.accent}55`,
                      color: m.accent,
                    }}
                  >
                    {m.initials}
                  </div>
                  <div>
                    <div className="text-[15px] font-medium text-white">{m.name}</div>
                    <div className="text-[12px] text-white/45">{m.provider}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-6 text-center text-[13px] text-white/45" data-testid="more-models-note">
            More models coming soon.
          </div>
        </section>

        {/* Trust strip */}
        <section id="pricing" className="mt-28 grid grid-cols-1 md:grid-cols-3 gap-4">
          <FeatureTile icon={Brain} title="Four minds, one verdict"  body="ChatGPT, Claude, Gemini and Grok reason on your question in parallel." />
          <FeatureTile icon={ShieldCheck} title="Consensus + confidence" body="Every conclusion ships with a consensus level and a defensible confidence score." />
          <FeatureTile icon={Zap} title="Challenge, don't accept" body="One click to have every model try to disprove the conclusion — and update it." />
        </section>
      </main>

      <footer className="relative border-t border-white/[0.06] py-8 text-center text-[12px] text-white/40">
        © {new Date().getFullYear()} AI Referee · The AI Consensus Platform
      </footer>
    </div>
  );
}

function SliderField({ icon: Icon, label, leftLabel, rightLabel, value, onChange, hint, testId }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-white/45">
          <Icon className="w-3.5 h-3.5" /> {label}
        </div>
        <span className="text-[11px] text-[#00E5FF]/80 font-mono" data-testid={`${testId}-hint`}>{hint}</span>
      </div>
      <div className="referee-slider px-1">
        <Slider min={0} max={100} step={1} value={[value]} onValueChange={(v) => onChange(v[0])} data-testid={testId} />
      </div>
      <div className="flex items-center justify-between text-[12px] text-white/50">
        <span>{leftLabel}</span>
        <span>{rightLabel}</span>
      </div>
    </div>
  );
}

function WorkflowStep({ index, title, body }) {
  return (
    <div className="relative rounded-2xl border border-white/[0.08] bg-[#0B1120]/70 backdrop-blur p-4 min-w-[190px] md:min-w-0">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[10px] font-mono text-[#00E5FF]/80 tracking-widest">0{index}</span>
        <span className="h-px flex-1 bg-white/[0.08]" />
      </div>
      <div className="text-[13.5px] font-medium text-white leading-tight">{title}</div>
      <div className="mt-1.5 text-[12px] text-white/50 leading-snug">{body}</div>
    </div>
  );
}

function FeatureTile({ icon: Icon, title, body }) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5 hover:bg-white/[0.04] transition-colors">
      <div className="w-9 h-9 rounded-lg bg-[#00E5FF]/10 border border-[#00E5FF]/20 flex items-center justify-center mb-4">
        <Icon className="w-4 h-4 text-[#00E5FF]" />
      </div>
      <div className="font-medium text-white">{title}</div>
      <p className="mt-1.5 text-[13px] text-white/55 leading-relaxed">{body}</p>
    </div>
  );
}

function SectionHeader({ eyebrow, title, body }) {
  return (
    <div className="max-w-2xl">
      <div className="text-[11px] uppercase tracking-[0.22em] text-[#00E5FF]/80 mb-3">{eyebrow}</div>
      <h2 className="text-2xl md:text-3xl font-semibold tracking-tight text-white leading-tight">{title}</h2>
      <p className="mt-3 text-[14.5px] text-white/55 leading-relaxed">{body}</p>
    </div>
  );
}
