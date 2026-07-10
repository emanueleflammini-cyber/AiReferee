import { useState, useRef, useEffect } from "react";
import { Globe, Check, ChevronDown } from "lucide-react";
import { useI18n, LANG_LABELS, SUPPORTED_LANGS } from "@/lib/i18n";

export function LanguageSelector({ testId = "language-selector" }) {
  const { lang, setLang } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div ref={ref} className="relative" data-testid={testId}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-[13px] text-white/80 hover:bg-white/[0.08] hover:text-white transition-colors"
        data-testid="lang-toggle"
      >
        <Globe className="w-3.5 h-3.5" />
        <span className="uppercase font-mono">{lang}</span>
        <ChevronDown className={"w-3 h-3 transition-transform " + (open ? "rotate-180" : "")} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-2 min-w-[180px] rounded-xl border border-white/10 bg-[#0B1120]/95 backdrop-blur-xl p-1 z-50"
          style={{ boxShadow: "0 20px 40px -12px rgba(0,0,0,0.6)" }}
          data-testid="lang-menu"
        >
          {SUPPORTED_LANGS.map((code) => (
            <button
              key={code}
              onClick={() => { setLang(code); setOpen(false); }}
              data-testid={`lang-option-${code}`}
              className={
                "w-full flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors " +
                (code === lang ? "bg-white/[0.06] text-white" : "text-white/70 hover:bg-white/[0.04] hover:text-white")
              }
            >
              <span>{LANG_LABELS[code]}</span>
              {code === lang && <Check className="w-3.5 h-3.5 text-[#00E5FF]" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
