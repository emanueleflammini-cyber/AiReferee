import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";
import { useI18n } from "@/lib/i18n";

/** Minimal installability chip.
 *  - Chromium / Android / Edge: uses `beforeinstallprompt`.
 *  - iOS Safari: shows a localized "Tap Share, then Add to Home Screen" popover.
 *  - Everywhere else, or once already installed: renders nothing.
 */
export function InstallButton() {
  const { t } = useI18n();
  const [deferred, setDeferred] = useState(null);
  const [showIosHint, setShowIosHint] = useState(false);

  const isIos = typeof navigator !== "undefined" &&
    /iphone|ipad|ipod/i.test(navigator.userAgent) &&
    !/CriOS|FxiOS|EdgiOS/i.test(navigator.userAgent);
  const isStandalone = typeof window !== "undefined" &&
    (window.matchMedia?.("(display-mode: standalone)").matches ||
     window.navigator?.standalone === true);

  useEffect(() => {
    const onPrompt = (e) => { e.preventDefault(); setDeferred(e); };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (isStandalone) return null;
  if (!deferred && !isIos) return null;

  const onClick = async () => {
    if (deferred) {
      deferred.prompt();
      try { await deferred.userChoice; } catch { /* user dismissed */ }
      setDeferred(null);
    } else if (isIos) {
      setShowIosHint(true);
    }
  };

  return (
    <>
      <button
        onClick={onClick}
        data-testid="pwa-install-button"
        className="inline-flex items-center gap-1.5 rounded-full border border-[#00E5FF]/40 bg-[#00E5FF]/[0.08] px-3 py-2 text-[12.5px] text-[#00E5FF] hover:bg-[#00E5FF]/[0.14] transition-colors"
      >
        <Download className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">{t("install.button")}</span>
      </button>

      {showIosHint && (
        <div
          data-testid="pwa-ios-hint"
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={() => setShowIosHint(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#0B1120] p-5 text-white"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="font-medium text-[15px]">{t("install.iosTitle")}</div>
              <button
                onClick={() => setShowIosHint(false)}
                data-testid="pwa-ios-hint-close"
                className="text-white/50 hover:text-white transition-colors"
                aria-label={t("install.dismiss")}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="mt-2 text-[13.5px] text-white/70 leading-relaxed">
              {t("install.iosBody")}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
