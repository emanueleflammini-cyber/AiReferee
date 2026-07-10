import { createContext, useContext, useState, useEffect } from "react";

const QueryContext = createContext(null);

const DEFAULT_SETTINGS = {
  reusePref: "ask", // ask | prefer_fresh | prefer_reused | never_sensitive
  answerLanguage: null,     // null = follow interface_language
  autoDetectQuestion: true, // detect question language automatically
};

function loadSettings() {
  try {
    const raw = localStorage.getItem("referee_settings");
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function QueryProvider({ children }) {
  const [query, setQuery] = useState({
    prompt: "",
    goal: 40,
    detail: 50,
    audience: "professional",
    format: "paragraph",
    strategy: "balanced",
  });

  const [settings, setSettingsState] = useState(loadSettings);

  useEffect(() => {
    try { localStorage.setItem("referee_settings", JSON.stringify(settings)); } catch { /* ignore storage errors */ }
  }, [settings]);

  const setSettings = (patch) => setSettingsState((prev) => ({ ...prev, ...patch }));

  return (
    <QueryContext.Provider value={{ query, setQuery, settings, setSettings }}>
      {children}
    </QueryContext.Provider>
  );
}

export function useQueryState() {
  const ctx = useContext(QueryContext);
  if (!ctx) throw new Error("useQueryState must be used inside QueryProvider");
  return ctx;
}
