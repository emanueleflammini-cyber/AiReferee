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
} from "lucide-react";
import { NavBar } from "@/components/NavBar";
import { Slider } from "@/components/ui/slider";
import { useQueryState } from "@/lib/QueryContext";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const AUDIENCES = [
  { id: "beginner", label: "Beginner" },
  { id: "professional", label: "Professional" },
  { id: "expert", label: "Expert" },
];

const FORMATS = [
  { id: "paragraph", label: "Paragraph", icon: LayoutList },
  { id: "bullets", label: "Bullet List", icon: LayoutList },
  { id: "table", label: "Table", icon: LayoutList },
  { id: "steps", label: "Step-by-step", icon: LayoutList },
];

export default function Home() {
  const navigate = useNavigate();
  const { query, setQuery } = useQueryState();
  const [submitting, setSubmitting] = useState(false);
  const taRef = useRef(null);

  const autosize = () => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 360) + "px";
  };

  useEffect(() => { autosize(); }, [query.prompt]);

  const handleCompare = async () => {
    if (!query.prompt.trim()) {
      toast.error("Ask something first — the referee can't judge silence.");
      taRef.current?.focus();
      return;
    }
    setSubmitting(true);
    try {
      await axios.post(`${API}/queries`, {
        prompt: query.prompt,
        goal: query.goal,
        detail: query.detail,
        audience: query.audience,
        format: query.format,
      });
    } catch (e) {
      // Non-blocking — the frontend can still show placeholder results
      console.warn("Query save failed", e);
    }
    setSubmitting(false);
    navigate("/results");
  };

  const goalLabel =
    query.goal < 33 ? "Leaning Accuracy" :
    query.goal > 66 ? "Leaning Creativity" : "Balanced";
  const detailLabel =
    query.detail < 33 ? "Quick take" :
    query.detail > 66 ? "Deep dive" : "Balanced";

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#060A14] text-white" data-testid="home-page">
      {/* Ambient background */}
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
            Multi-model consensus, on demand
          </div>
          <h1
            className="text-5xl sm:text-6xl md:text-7xl font-semibold tracking-tighter leading-[1.02]"
            data-testid="hero-title"
          >
            AI <span className="shimmer-text">Referee</span>
          </h1>
          <p className="mt-6 text-lg md:text-xl text-white/60 max-w-2xl mx-auto leading-relaxed" data-testid="hero-subtitle">
            <span className="text-white/90">One Question.</span>{" "}
            <span className="text-white/70">Multiple AIs.</span>{" "}
            <span className="text-white/90">One Super Answer.</span>
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
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleCompare();
                }}
              />
            </div>

            {/* Filters row */}
            <div className="border-t border-white/[0.06] bg-[#080D18]/40 px-6 md:px-8 py-6 space-y-6">
              {/* Sliders row */}
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

              {/* Audience */}
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

              {/* Output format */}
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

          {/* Compare button */}
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-4 text-[12px] text-white/45">
              <span className="hidden sm:inline">Press ⌘/Ctrl + Enter to submit</span>
            </div>
            <button
              onClick={handleCompare}
              disabled={submitting}
              data-testid="compare-ais-button"
              className="group inline-flex items-center gap-2.5 rounded-full bg-[#0066FF] hover:bg-[#0052CC] text-white font-medium px-7 py-3.5 text-[15px] transition-colors disabled:opacity-70"
              style={{ boxShadow: "0 0 0 1px rgba(255,255,255,0.08) inset, 0 20px 40px -12px rgba(0,102,255,0.6)" }}
            >
              <Sparkles className="w-4 h-4 transition-transform group-hover:rotate-12" />
              {submitting ? "Summoning models..." : "Compare AIs"}
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </button>
          </div>
        </motion.div>

        {/* Trust strip */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.35 }}
          className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-4"
          id="how"
        >
          <FeatureTile
            icon={Brain}
            title="Four models, one verdict"
            body="Nova, Ember, Prism and Kairo debate your question in parallel."
          />
          <FeatureTile
            icon={ShieldCheck}
            title="Consensus scored"
            body="Every answer ships with a consensus and trust score you can see."
          />
          <FeatureTile
            icon={Zap}
            title="Built for speed"
            body="Streaming responses. Sub-second Super Answers on short prompts."
          />
        </motion.div>
      </main>

      <footer className="relative border-t border-white/[0.06] py-8 text-center text-[12px] text-white/40">
        © {new Date().getFullYear()} AI Referee · Consensus for the AI era
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
        <Slider
          min={0}
          max={100}
          step={1}
          value={[value]}
          onValueChange={(v) => onChange(v[0])}
          data-testid={testId}
        />
      </div>
      <div className="flex items-center justify-between text-[12px] text-white/50">
        <span>{leftLabel}</span>
        <span>{rightLabel}</span>
      </div>
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
