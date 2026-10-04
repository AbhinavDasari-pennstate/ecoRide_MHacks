import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { userById, useMainTrip } from "@/lib/store";

export function CountUp({
  to,
  decimals = 0,
  prefix = "",
  suffix = "",
  duration = 1400,
}: {
  to: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
}) {
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
  return (
    <span className="num">
      {prefix}
      {v.toFixed(decimals)}
      {suffix}
    </span>
  );
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
    <span
      key={status}
      className={cn(
        "animate-pop inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold tracking-wide",
        pillStyles[status] ?? pillStyles["NONE"],
      )}
    >
      {status === "REOPTIMIZING" || status === "MATCHING" ? (
        <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        <span className="size-1.5 rounded-full bg-current" />
      )}
      {label ?? (status === "NONE" ? "NO CAR YET" : status === "LOST" ? "VEHICLE LOST" : status)}
    </span>
  );
}

export function Avatar({ id, size = 40, ring }: { id: string; size?: number; ring?: boolean }) {
  const u = userById(id);
  return (
    <div
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-bold text-cream",
        ring && "ring-4 ring-card",
      )}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.36,
        background: `oklch(0.52 0.08 ${(u.hue % 90) + 20})`,
      }}
      title={u.name}
    >
      {u.initials}
    </div>
  );
}

export function RoleBadge({ role }: { role: string }) {
  return (
    <span className="rounded-md bg-accent px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-accent-foreground">
      {role}
    </span>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("card-surface p-6", className)}>{children}</div>;
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
      {children}
    </div>
  );
}

export function RouteMap({ className }: { className?: string }) {
  const trip = useMainTrip();
  const stops = trip?.stops ?? [];
  if (!stops.length)
    return (
      <div className="p-10 text-center text-muted-foreground">Route appears after matching.</div>
    );
  const minLat = Math.min(...stops.map((s) => s.lat));
  const maxLat = Math.max(...stops.map((s) => s.lat));
  const minLng = Math.min(...stops.map((s) => s.lng));
  const maxLng = Math.max(...stops.map((s) => s.lng));
  const points = stops.map((s) => ({
    ...s,
    x: 45 + ((s.lng - minLng) / (maxLng - minLng || 1)) * 270,
    y: 175 - ((s.lat - minLat) / (maxLat - minLat || 1)) * 130,
  }));
  return (
    <svg
      viewBox="0 0 400 220"
      role="img"
      aria-label="Schematic of pickup stops from the backend"
      className={cn("w-full rounded-xl bg-card", className)}
    >
      <polyline
        points={points.map((p) => `${p.x},${p.y}`).join(" ")}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="3"
      />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r={6} fill="var(--green)" />
          <text x={p.x + 10} y={p.y - 10} fontSize="11" fill="var(--forest)">
            {p.name}
          </text>
        </g>
      ))}
      <text x="20" y="210" fontSize="10" fill="var(--forest)">
        Pickup sequence ? schematic, not turn-by-turn navigation
      </text>
    </svg>
  );
}
