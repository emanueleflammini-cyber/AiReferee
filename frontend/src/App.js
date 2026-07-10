import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Home from "@/pages/Home";
import Results from "@/pages/Results";
import Debate from "@/pages/Debate";
import ReuseFound from "@/pages/ReuseFound";
import Settings from "@/pages/Settings";
import { Toaster } from "sonner";
import { QueryProvider } from "@/lib/QueryContext";
import { I18nProvider } from "@/lib/i18n";

function App() {
  return (
    <div className="App">
      <I18nProvider>
        <QueryProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/reuse-found" element={<ReuseFound />} />
            <Route path="/results" element={<Results />} />
            <Route path="/debate" element={<Debate />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </BrowserRouter>
        </QueryProvider>
      </I18nProvider>
      <Toaster
        position="bottom-right"
        theme="dark"
        toastOptions={{
          style: {
            background: "#0D1424",
            border: "1px solid rgba(255,255,255,0.08)",
            color: "#fff",
          },
        }}
      />
    </div>
  );
}

export default App;
