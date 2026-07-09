import { Logo } from "@/components/Logo";
import { Link } from "react-router-dom";

export function NavBar({ variant = "home" }) {
  return (
    <header
      className="sticky top-0 z-40 w-full"
      data-testid="site-navbar"
    >
      <div className="absolute inset-0 bg-[#060A14]/70 backdrop-blur-xl border-b border-white/[0.06]" />
      <nav className="relative mx-auto flex max-w-7xl items-center justify-between px-5 md:px-8 py-4">
        <Logo />
        <div className="hidden md:flex items-center gap-8 text-[13px] text-white/60">
          <a href="#how" className="hover:text-white transition-colors" data-testid="nav-how">How it works</a>
          <a href="#models" className="hover:text-white transition-colors" data-testid="nav-models">Models</a>
          <a href="#pricing" className="hover:text-white transition-colors" data-testid="nav-pricing">Pricing</a>
        </div>
        <div className="flex items-center gap-3">
          {variant !== "home" && (
            <Link
              to="/"
              className="text-[13px] text-white/70 hover:text-white transition-colors"
              data-testid="nav-new-question"
            >
              New question
            </Link>
          )}
          <button
            className="hidden sm:inline-flex items-center rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-[13px] text-white/80 hover:bg-white/[0.08] hover:text-white transition-colors"
            data-testid="nav-signin"
          >
            Sign in
          </button>
        </div>
      </nav>
    </header>
  );
}
