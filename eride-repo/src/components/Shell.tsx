import { useEffect } from "react";
import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import { Wordmark } from "./Logo";
import { APP_NAME, setUi, useStore } from "@/lib/store";
import { reset } from "@/lib/demo";

export function ProfileLink() {
  return (
    <Link to="/profile" className="flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-sm font-semibold transition hover:bg-sand">
      <span className="grid size-8 place-items-center rounded-full bg-walnut text-xs font-bold text-cream">AR</span>
      Profile
    </Link>
  );
}

export function Shell() {
  const banner = useStore((s) => s.ui.banner);
  const nav = useNavigate();
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.shiftKey && e.key.toLowerCase() === "r" && !(e.target as HTMLElement).closest("input,textarea")) {
        reset();
        setUi({ banner: "Demo reset" });
        setTimeout(() => setUi({ banner: undefined }), 1800);
        nav({ to: "/" });
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [nav]);
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between px-6 py-5 md:px-10">
        <Link to="/" aria-label={APP_NAME}><Wordmark /></Link>
        <ProfileLink />
      </header>
      <Outlet />
      {banner && <div className="fixed left-1/2 top-6 z-50 -translate-x-1/2 animate-pop rounded-full bg-forest px-6 py-3 font-bold text-cream shadow-float">{banner}</div>}
    </div>
  );
}
