import { createContext, useContext, useState } from "react";

const QueryContext = createContext(null);

export function QueryProvider({ children }) {
  const [query, setQuery] = useState({
    prompt: "",
    goal: 40,
    detail: 50,
    audience: "professional",
    format: "paragraph",
    strategy: "balanced",
  });

  return (
    <QueryContext.Provider value={{ query, setQuery }}>
      {children}
    </QueryContext.Provider>
  );
}

export function useQueryState() {
  const ctx = useContext(QueryContext);
  if (!ctx) throw new Error("useQueryState must be used inside QueryProvider");
  return ctx;
}
