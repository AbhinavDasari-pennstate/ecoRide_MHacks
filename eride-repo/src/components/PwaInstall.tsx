import { useEffect, useState } from "react";
import { Download, Smartphone } from "lucide-react";

type InstallPrompt = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

let registration: Promise<ServiceWorkerRegistration> | undefined;

export function PwaInstall() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  const [ios, setIos] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const isInstalled =
      window.matchMedia("(display-mode: standalone)").matches ||
      (navigator as Navigator & { standalone?: boolean }).standalone === true;
    setInstalled(isInstalled);
    const agent = navigator.userAgent;
    const iosDevice =
      /iPad|iPhone|iPod/.test(agent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    setIos(iosDevice && /Safari/.test(agent) && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(agent));

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallPrompt);
      setError(null);
    };
    const onInstalled = () => {
      setInstalled(true);
      setPrompt(null);
      setError(null);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);

    if ("serviceWorker" in navigator && window.isSecureContext) {
      registration ??= navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((cause) => {
        registration = undefined;
        throw cause;
      });
      void registration.catch(() => {
        if (mounted) setError("App installation isn't available right now. Refresh to try again.");
      });
    }
    return () => {
      mounted = false;
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  async function install() {
    if (!prompt || installing) return;
    setInstalling(true);
    setError(null);
    try {
      await prompt.prompt();
      const choice = await prompt.userChoice;
      if (choice.outcome === "accepted") setInstalled(true);
    } catch {
      setError("Installation didn't open. Use your browser menu to install ERIDE.");
    } finally {
      setPrompt(null);
      setInstalling(false);
    }
  }

  if (!error && (installed || (!prompt && !ios))) return null;

  return (
    <aside aria-label="Install ERIDE" className="mt-auto border-t border-border px-6 py-4 md:px-10">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 text-sm">
        {error ? (
          <p role="status" className="text-muted-foreground">
            {error}
          </p>
        ) : (
          <>
            <p className="flex items-center gap-2 text-muted-foreground">
              <Smartphone size={17} aria-hidden="true" /> Add ERIDE to your device.
            </p>
            {prompt ? (
              <button
                type="button"
                disabled={installing}
                onClick={() => void install()}
                className="inline-flex min-h-11 items-center gap-2 rounded-full bg-sand px-4 py-2 font-bold text-forest transition hover:bg-lime focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-forest disabled:opacity-60"
              >
                <Download size={16} aria-hidden="true" />{" "}
                {installing ? "Opening installer…" : "Install ERIDE"}
              </button>
            ) : (
              <details className="max-w-sm text-forest">
                <summary className="min-h-11 cursor-pointer rounded-full bg-sand px-4 py-3 font-bold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-forest">
                  Add ERIDE to your home screen
                </summary>
                <p className="px-4 pt-3 text-sm leading-relaxed text-muted-foreground">
                  In Safari, tap Share, then Add to Home Screen, and tap Add.
                </p>
              </details>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
