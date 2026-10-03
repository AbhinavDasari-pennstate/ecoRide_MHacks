import { useEffect } from "react";
import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import { Wordmark } from "./Logo";
import { APP_NAME, setUi, useStore } from "@/lib/store";
import { reset } from "@/lib/demo";
import { initialize, refresh, perform } from "@/lib/api";

export function ProfileLink() {
  return (
    <Link
      to="/profile"
      className="flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-sm font-semibold transition hover:bg-sand"
    >
      <span className="grid size-8 place-items-center rounded-full bg-walnut text-xs font-bold text-cream">
        AR
      </span>
      Profile
    </Link>
  );
}

export function Shell() {
  const banner = useStore((s) => s.ui.banner);
  const ready = useStore((s) => s.ready);
  const error = useStore((s) => s.error);
  const busy = useStore((s) => s.busy);
  const nav = useNavigate();
  useEffect(() => {
    void perform(initialize);
    const timer = setInterval(() => {
      if (useStore.getState().ready && !useStore.getState().busy) void perform(refresh);
    }, 4000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (
        e.shiftKey &&
        e.key.toLowerCase() === "r" &&
        !(e.target as HTMLElement).closest("input,textarea")
      ) {
        e.preventDefault();
        void perform(async () => {
          await reset();
          await nav({ to: "/" });
        });
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [nav]);
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between px-6 py-5 md:px-10">
        <Link to="/" aria-label={APP_NAME}>
          <Wordmark />
        </Link>
        <ProfileLink />
      </header>
      <div className="px-6 pb-4 text-xs text-muted-foreground md:px-10">
        Live database · Guided demo accounts · Voice and phone panels are simulations
      </div>
      {error && (
        <div role="alert" className="mx-6 mb-4 rounded-xl border border-destructive p-4 text-sm">
          {error}{" "}
          <button
            className="ml-3 font-bold underline"
            onClick={() =>
              void perform(async () => {
                await initialize();
                await refresh();
                useStore.setState({ error: null });
              })
            }
          >
            Retry connection
          </button>
          <button className="ml-3 underline" onClick={() => useStore.setState({ error: null })}>
            Dismiss
          </button>
        </div>
      )}
      {busy && (
        <div role="status" className="px-6 pb-3 text-sm text-primary">
          Saving and updating your trip…
        </div>
      )}
      {ready ? (
        <Outlet />
      ) : (
        <main className="p-10 text-center" role="status">
          {error
            ? "Waiting for the backend. Use Retry connection above."
            : "Connecting to your trips…"}
        </main>
      )}
      {banner && (
        <div className="fixed left-1/2 top-6 z-50 -translate-x-1/2 animate-pop rounded-full bg-forest px-6 py-3 font-bold text-cream shadow-float">
          {banner}
        </div>
      )}
    </div>
  );
}
