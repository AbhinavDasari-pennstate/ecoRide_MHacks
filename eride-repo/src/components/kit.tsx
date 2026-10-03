import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { userById } from "@/lib/store";

export function CountUp({ to, decimals = 0, prefix = "", suffix = "", duration = 1400 }: { to: number; decimals?: number; prefix?: string; suffix?: string; duration?: number }) {
  const [v, setV] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const start = performance.now();
    const f0 = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const e = 1 - Math.pow(1 - p, 3);
      const val = f0 + (to - f0) * e;
      setV(val);
      if (p < 1) raf = requestAnimationFrame(tick);
      else from.current = to;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, duration]);
  return <span className="num">{prefix}{v.toFixed(decimals)}{suffix}</span>;
}

const pillStyles: Record<string, string> = {
  PENDING: "bg-warning/25 text-foreground",
  CONFIRMED: "bg-lime text-lime-foreground",
  RESERVED: "bg-walnut text-cream",
  AVAILABLE: "bg-secondary text-secondary-foreground",
  APPROVED: "bg-walnut text-cream",
  DECLINED: "bg-destructive/15 text-destructive",
  CANCELLED: "bg-destructive/15 text-destructive",
  LOST: "bg-destructive text-destructive-foreground",
  REOPTIMIZING: "bg-primary text-primary-foreground",
  REQUESTED: "bg-secondary text-secondary-foreground",
  MATCHING: "bg-primary text-primary-foreground",
  NONE: "bg-muted text-muted-foreground",
};
export function StatusPill({ status, label }: { status: string; label?: string }) {
  return (
    <span key={status} className={cn("animate-pop inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold tracking-wide", pillStyles[status] ?? pillStyles["NONE"])}>
      {status === "REOPTIMIZING" || status === "MATCHING" ? <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <span className="size-1.5 rounded-full bg-current" />}
      {label ?? (status === "NONE" ? "NO CAR YET" : status === "LOST" ? "VEHICLE LOST" : status)}
    </span>
  );
}

export function Avatar({ id, size = 40, ring }: { id: string; size?: number; ring?: boolean }) {
  const u = userById(id);
  return (
    <div
      className={cn("grid shrink-0 place-items-center rounded-full font-bold text-cream", ring && "ring-4 ring-card")}
      style={{ width: size, height: size, fontSize: size * 0.36, background: `oklch(0.52 0.08 ${(u.hue % 90) + 20})` }}
      title={u.name}
    >
      {u.initials}
    </div>
  );
}

export function RoleBadge({ role }: { role: string }) {
  return <span className="rounded-md bg-accent px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-accent-foreground">{role}</span>;
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("card-surface p-6", className)}>{children}</div>;
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{children}</div>;
}

export function RouteMap({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 400 220" className={cn("w-full rounded-xl bg-card", className)}>
      <defs>
        <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <path d="M28 0H0V28" fill="none" stroke="var(--border)" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="400" height="220" fill="url(#grid)" />
      <path d="M0 150 Q120 120 200 160 T400 130" stroke="var(--muted)" strokeWidth="14" fill="none" />
      <path d="M90 0 L130 220" stroke="var(--muted)" strokeWidth="10" />
      <path d="M290 0 L270 220" stroke="var(--muted)" strokeWidth="10" />
      <ellipse cx="330" cy="50" rx="50" ry="22" fill="var(--muted)" />
      <path className="animate-route" d="M60 60 C110 70 120 120 160 140 S250 170 280 120 S330 70 340 60" stroke="var(--primary)" strokeWidth="3.5" fill="none" strokeLinecap="round" />
      {[[60, 60, "Campus"], [160, 140, "Maya"], [255, 155, "Jordan"], [340, 60, "Meijer"]].map(([x, y, l], i) => (
        <g key={i}>
          <circle cx={x as number} cy={y as number} r={i === 3 ? 8 : 5} fill={i === 3 ? "var(--green)" : "var(--primary)"} stroke="var(--card)" strokeWidth="3" />
          <text x={(x as number) + 12} y={(y as number) - 10} fontSize="12" fontWeight="700" fill="var(--forest)">{l}</text>
        </g>
      ))}
    </svg>
  );
}
