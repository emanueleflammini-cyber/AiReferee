import { Link, useLocation } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { LanguageSelector } from "@/components/LanguageSelector";
import { InstallButton } from "@/components/InstallButton";
import { Settings as SettingsIcon } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function NavBar({ variant = "home" }) {
  const loc = useLocation();
  const { t } = useI18n();
  return (
    <header className="sticky top-0 z-40 w-full" data-testid="site-navbar">
      <div className="absolute inset-0 bg-[#060A14]/70 backdrop-blur-xl border-b border-white/[0.06]" />
      <nav className="relative mx-auto flex max-w-7xl items-center justify-between px-5 md:px-8 py-4">
        <Logo />
        <div className="hidden md:flex items-center gap-8 text-[13px] text-white/60">
          <a href="/#how" className="hover:text-white transition-colors" data-testid="nav-how">{t("nav.howItWorks")}</a>
          <a href="/#models" className="hover:text-white transition-colors" data-testid="nav-models">{t("nav.models")}</a>
          <a href="/#pricing" className="hover:text-white transition-colors" data-testid="nav-pricing">{t("nav.pricing")}</a>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          {variant !== "home" && (
            <Link to="/" className="text-[13px] text-white/70 hover:text-white transition-colors" data-testid="nav-new-question">
              {t("nav.newQuestion")}
            </Link>
          )}
          <LanguageSelector />
          <InstallButton />
          <Link
            to="/settings" state={{ from: loc.pathname }}
            data-testid="nav-settings"
            title={t("nav.settings")}
            className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-[13px] text-white/80 hover:bg-white/[0.08] hover:text-white transition-colors"
          >
            <SettingsIcon className="w-3.5 h-3.5" />
          </Link>
        </div>
      </nav>
    </header>
  );
}
