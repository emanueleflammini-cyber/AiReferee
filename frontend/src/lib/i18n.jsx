import { useContext, createContext, useEffect, useState, useCallback } from "react";
import en from "@/locales/en.json";
import it from "@/locales/it.json";
import es from "@/locales/es.json";
import fr from "@/locales/fr.json";
import de from "@/locales/de.json";
import pt from "@/locales/pt.json";

const BUNDLES = { en, it, es, fr, de, pt };
export const SUPPORTED_LANGS = ["en", "it", "es", "fr", "de", "pt"];
export const LANG_LABELS = { en: "English", it: "Italiano", es: "Español", fr: "Français", de: "Deutsch", pt: "Português" };

const I18nContext = createContext(null);

function detectBrowserLang() {
  try {
    const stored = localStorage.getItem("referee_interface_lang");
    if (stored && SUPPORTED_LANGS.includes(stored)) return stored;
    const nav = (navigator.language || navigator.userLanguage || "en").slice(0, 2).toLowerCase();
    return SUPPORTED_LANGS.includes(nav) ? nav : "en";
  } catch {
    return "en";
  }
}

function get(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(detectBrowserLang);

  useEffect(() => {
    try { localStorage.setItem("referee_interface_lang", lang); } catch { /* ignore storage errors */ }
    document.documentElement.lang = lang;
  }, [lang]);

  const t = useCallback((key, vars) => {
    let s = get(BUNDLES[lang], key);
    if (s == null) s = get(BUNDLES.en, key);
    if (s == null) return key;
    if (vars) {
      Object.entries(vars).forEach(([k, v]) => {
        s = s.replace(new RegExp(`\\{${k}\\}`, "g"), v);
      });
    }
    return s;
  }, [lang]);

  return (
    <I18nContext.Provider value={{ lang, setLang, t, supported: SUPPORTED_LANGS }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be inside <I18nProvider>");
  return ctx;
}
