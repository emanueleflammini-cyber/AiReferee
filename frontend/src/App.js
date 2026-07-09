import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Home from "@/pages/Home";
import Results from "@/pages/Results";
import Debate from "@/pages/Debate";
import { Toaster } from "sonner";
import { QueryProvider } from "@/lib/QueryContext";

function App() {
  return (
    <div className="App">
      <QueryProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/results" element={<Results />} />
            <Route path="/debate" element={<Debate />} />
          </Routes>
        </BrowserRouter>
      </QueryProvider>
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
