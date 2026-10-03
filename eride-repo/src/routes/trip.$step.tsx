import { useEffect } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Check, ChevronRight, Fuel, Mic, Sparkles, X, Zap } from "lucide-react";
import { useMainTrip, useStore, userById, MAIN_TRIP } from "@/lib/store";
import { reserve_vehicle } from "@/lib/api";
import * as d from "@/lib/demo";
import { Avatar, Card, CountUp, Eyebrow, RouteMap, StatusPill } from "@/components/kit";
import { Phone } from "@/components/Phone";
import { ImpactSummary } from "@/components/Impact";
import { TripCard } from "@/components/TripCard";
import { cn } from "@/lib/utils";

const STEPS = [
  { label: "Voice request", title: "Tell ERIDE where you're headed.", sub: "Just talk. We'll turn it into a trip request." },
  { label: "Matching", title: "Compatible travelers found.", sub: "Riders heading the same way at the same time join your trip." },
  { label: "Vehicle selection", title: "Two cars fit your window.", sub: "Saturday 1:45 to 4:15 PM, 3 riders, 14.1 miles." },
  { label: "Rider confirms via text", title: "Maya gets a text.", sub: "No app needed. Riders confirm with one reply." },
  { label: "Owner approves via text", title: "Sam approves the rental.", sub: "The car owner says yes from their phone." },
  { label: "Impact summary", title: "Here's what sharing saved.", sub: "Compared with three separate trips." },
  { label: "Disruption", title: "Plans change. The trip doesn't.", sub: "If a car drops out, ERIDE finds the next cleanest option." },
];

export const Route = createFileRoute("/trip/$step")({
  head: ({ params }) => {
    const n = Number(params.step);
    const s = STEPS[n - 1];
    const title = s ? `Step ${n}: ${s.label} | ERIDE` : "Trip confirmed | ERIDE";
    const desc = s ? s.sub : "Your shared grocery trip is confirmed.";
    return { meta: [{ title }, { name: "description", content: desc }, { property: "og:title", content: title }, { property: "og:description", content: desc }] };
  },
  component: Flow,
});

function Flow() {
  const { step } = Route.useParams();
  const nav = useNavigate();
  const n = step === "done" ? 8 : Math.min(7, Math.max(1, Number(step) || 1));
  const voiceLine = useStore((s) => s.ui.voiceLine);
  const voiceBusy = useStore((s) => s.ui.voiceBusy);
  const hasTrip = !!useMainTrip();
  const locked = n === 1 && !(voiceLine >= d.SCRIPT.length && !voiceBusy && hasTrip);

  const go = (k: number) => nav({ to: "/trip/$step", params: { step: k >= 8 ? "done" : String(k) } });
  const next = () => { if (!locked && n < 8) go(n + 1); };
  const back = () => (n > 1 ? go(n - 1) : nav({ to: "/" }));

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea,[role=dialog]")) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (n === 1 && locked) d.advanceVoice(); else next();
      } else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  if (n === 8) return <Done />;
  const s = STEPS[n - 1]!;
  return (
    <div className="flex flex-1 flex-col">
      <div className="px-6 md:px-10">
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold">Step {n} of 7: {s.label}</span>
          <Link to="/" className="flex items-center gap-1 text-muted-foreground hover:text-foreground"><X className="size-4" /> Exit</Link>
        </div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-green transition-all duration-500" style={{ width: `${(n / 7) * 100}%` }} /></div>
      </div>
      <main key={n} className="mx-auto flex w-full max-w-6xl flex-1 animate-step flex-col items-center px-6 pb-32 pt-10 text-center md:px-10">
        <h1 className="max-w-3xl text-3xl font-semibold tracking-tight md:text-5xl">{s.title}</h1>
        <p className="mt-3 max-w-xl text-lg text-muted-foreground">{s.sub}</p>
        <div className="mt-10 w-full">
          {n === 1 && <StepVoice />}
          {n === 2 && <StepMatching />}
          {n === 3 && <StepVehicles />}
          {n === 4 && <StepRider />}
          {n === 5 && <StepOwner />}
          {n === 6 && <ImpactSummary />}
          {n === 7 && <StepDisruption />}
        </div>
      </main>
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4 md:px-10">
          <button onClick={back} className="flex items-center gap-2 rounded-full px-5 py-3 font-semibold transition hover:bg-sand"><ArrowLeft className="size-4" /> Back</button>
          <button onClick={next} disabled={locked} className="flex items-center gap-2 rounded-full bg-primary px-7 py-3 font-bold text-primary-foreground transition hover:brightness-105 active:scale-[0.97] disabled:opacity-40">
            {n === 7 ? "Finish" : "Continue"} <ArrowRight className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function StepVoice() {
  const step = useStore((s) => s.ui.voiceLine);
  const busy = useStore((s) => s.ui.voiceBusy);
  const t = useMainTrip();
  const speaking = step > 0 ? d.SCRIPT[step - 1]!.who : "agent";
  const done = step >= d.SCRIPT.length;
  return (
    <div className="mx-auto w-full max-w-2xl space-y-5">
      <div className="rounded-[2rem] border border-border bg-card p-8 text-left shadow-float">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-full bg-primary text-primary-foreground"><Mic className="size-5" /></span>
            <div><div className="text-xs uppercase tracking-[0.18em] opacity-60">Voice call</div><div className="text-lg font-bold">ERIDE Assistant</div></div>
          </div>
          <div className="num text-sm opacity-70">00:{String(8 + step * 6).padStart(2, "0")}</div>
        </div>
        <div className="my-8 flex h-20 items-center justify-center gap-1.5">
          {Array.from({ length: 32 }).map((_, i) => (
            <span key={i} className="animate-wave w-1 rounded-full bg-primary" style={{ height: `${24 + ((i * 37) % 52)}px`, animationDelay: `${(i % 7) * 0.09}s`, animationDuration: speaking === "agent" ? "0.8s" : "1.2s", opacity: done ? 0.3 : 1 }} />
          ))}
        </div>
        <div className="min-h-40 space-y-3">
          {d.SCRIPT.slice(0, step).map((l, i) => (
            <div key={i} className={`animate-fade-in ${l.who === "agent" ? "" : "text-right"}`}>
              <div className="text-[10px] font-semibold uppercase tracking-widest opacity-50">{l.who === "agent" ? "ERIDE" : "Alex"}</div>
              <div className={`mt-1 inline-block max-w-[85%] rounded-2xl px-4 py-2 text-[15px] ${l.who === "agent" ? "border border-border bg-card" : "bg-sand"}`}>{l.text}</div>
            </div>
          ))}
          {busy && <div className="text-sm opacity-70">Creating trip...</div>}
          {step === 0 && <div className="pt-8 text-center text-sm opacity-60">Press space or Next line to start the conversation</div>}
        </div>
        <div className="mt-6 flex justify-end">
          <button onClick={() => d.advanceVoice()} disabled={done || busy} className="flex items-center gap-2 rounded-full bg-primary px-5 py-3 font-semibold text-primary-foreground disabled:opacity-40">
            {done ? "Call ended" : "Next line"} <ChevronRight className="size-4" />
            <kbd className="rounded bg-muted px-1.5 text-[10px]">SPACE</kbd>
          </button>
        </div>
      </div>
      {done && t && (
        <Card className="mx-auto flex max-w-md animate-pop items-center gap-3 text-left">
          <span className="grid size-9 place-items-center rounded-full bg-lime text-lime-foreground"><Check className="size-5" /></span>
          <div className="font-semibold">Trip request created: Meijer, Sat 2:00 PM</div>
        </Card>
      )}
    </div>
  );
}

function StepMatching() {
  const t = useMainTrip();
  useEffect(() => { d.ensureMatches(); }, []);
  const riders = t?.participants ?? [];
  return (
    <div className="grid gap-6 text-left lg:grid-cols-[1fr_1.3fr]">
      <div className="space-y-3">
        {riders.map((p) => (
          <Card key={p.userId} className="flex animate-fade-in items-center gap-4 p-5">
            <Avatar id={p.userId} size={48} />
            <div className="flex-1">
              <div className="text-lg font-bold">{userById(p.userId).name}</div>
              <div className="text-sm text-muted-foreground">{p.role === "Driver" ? "Driver, needs a car" : `Passenger · ${userById(p.userId).dorm}`}</div>
            </div>
            {p.matchPct ? <div className="text-right"><div className="text-3xl font-semibold text-primary"><CountUp to={p.matchPct} suffix="%" /></div><div className="text-[10px] uppercase tracking-widest text-muted-foreground">match</div></div> : <StatusPill status="CONFIRMED" label="YOU" />}
          </Card>
        ))}
        {riders.length < 3 && <div className="flex items-center gap-2 p-4 text-muted-foreground"><span className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" /> Looking for compatible travelers...</div>}
        {riders.length >= 3 && <div className="animate-fade-in px-1 py-2 text-muted-foreground">Grouped into one trip · Vehicle required: <span className="text-primary">yes</span></div>}
      </div>
      <Card className="p-3"><RouteMap /></Card>
    </div>
  );
}

function StepVehicles() {
  const t = useMainTrip();
  const vehicles = useStore((s) => s.vehicles);
  useEffect(() => { d.ensureVehicle(); }, []);
  const selected = t?.vehicleId ?? "tesla";
  return (
    <div className="space-y-6 text-left">
      <div className="grid gap-6 md:grid-cols-2">
        {["tesla", "civic"].map((id) => {
          const v = vehicles.find((x) => x.id === id)!;
          const on = selected === id;
          const ev = v.type === "EV";
          return (
            <Card key={id} className={cn("relative transition", on && "ring-4 ring-primary")}>
              {on && <div className="absolute -top-3 left-6 animate-pop rounded-full bg-primary px-3 py-1 text-xs font-bold text-primary-foreground">AUTO-SELECTED</div>}
              <div className="flex items-center justify-between">
                <div className={cn("grid size-14 place-items-center rounded-2xl", ev ? "bg-lime text-lime-foreground" : "bg-sand text-walnut")}>{ev ? <Zap /> : <Fuel />}</div>
                <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-bold", ev ? "bg-lime text-lime-foreground" : "bg-sand")}>{ev ? "EV" : "GAS"}</span>
              </div>
              <h2 className="mt-4 text-2xl font-semibold">{v.name}</h2>
              <div className="text-sm text-muted-foreground">{v.color} · owned by {userById(v.ownerId).name}</div>
              <dl className="mt-6 grid grid-cols-3 gap-3">
                {[["Distance", `${v.distanceMi} mi`], ["Rate", `$${v.rate}/hr`], ["Trip CO2", `${(14.1 * v.kgPerMi).toFixed(1)} kg`]].map(([k, val]) => (
                  <div key={k} className=""><dt className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{k}</dt><dd className="num text-xl font-bold">{val}</dd></div>
                ))}
              </dl>
              {t && !on && <button onClick={() => reserve_vehicle(MAIN_TRIP, id)} className="mt-5 w-full rounded-xl border border-border py-2.5 text-sm font-semibold transition hover:bg-sand">Choose this instead</button>}
            </Card>
          );
        })}
      </div>
      <div className="flex items-start gap-3 border-t border-border pt-6 text-muted-foreground">
        <Sparkles className="mt-0.5 size-5 shrink-0 text-green" />
        <p className="text-base">Closest car is gas and slightly cheaper, but we prioritize the lowest-emissions feasible option.</p>
      </div>
    </div>
  );
}

function PhoneLayout({ userId, children }: { userId: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-10 md:flex-row">
      <Phone userId={userId} />
      <div className="w-full max-w-sm space-y-4 text-left">{children}</div>
    </div>
  );
}

function StepRider() {
  const t = useMainTrip();
  useEffect(() => { d.step4(); }, []);
  const maya = t?.participants.find((p) => p.userId === "maya");
  return (
    <PhoneLayout userId="maya">
      <Card>

        <div className="flex items-center gap-3">
          <Avatar id="maya" size={44} />
          <div className="flex-1"><div className="font-bold">Maya Chen</div><div className="text-sm text-muted-foreground">Passenger · 94% match</div></div>
          {maya && <StatusPill status={maya.status} />}
        </div>
      </Card>
    </PhoneLayout>
  );
}

function StepOwner() {
  const t = useMainTrip();
  const vehicles = useStore((s) => s.vehicles);
  useEffect(() => { d.step5(); }, []);
  const v = vehicles.find((x) => x.id === (t?.vehicleId ?? "tesla"))!;
  return (
    <PhoneLayout userId="sam">
      <Card>
        <div className="flex items-center justify-between"><Eyebrow>Vehicle</Eyebrow><StatusPill status={t?.vehicleState ?? "PENDING"} /></div>
        <div className="mt-2 text-2xl font-bold">{v.name}</div>
        <div className="text-sm text-muted-foreground">Owner Sam Patel · Sat 1:45 to 4:15 PM</div>
      </Card>
      <Card>
        <div className="flex items-center justify-between"><Eyebrow>Trip</Eyebrow>{t && <StatusPill status={t.status} />}</div>
        <div className="mt-2 text-lg font-bold">Meijer, Sat 2:00 PM</div>
      </Card>
    </PhoneLayout>
  );
}

function StepDisruption() {
  const t = useMainTrip();
  const phase = useStore((s) => s.ui.disruption);
  useEffect(() => { d.ensureVehicle(); }, []);
  if (!t) return null;
  return (
    <div className="space-y-8">
      {phase === "idle" && (
        <button onClick={() => d.simulateCancellation()} className="rounded-full border-2 border-destructive px-6 py-3 font-bold text-destructive transition hover:bg-destructive hover:text-destructive-foreground">
          Simulate vehicle cancellation
        </button>
      )}
      <div className={cn("grid items-start gap-8", phase === "done" && "lg:grid-cols-[1fr_auto]")}>
        <TripCard t={t} />
        {phase === "done" && <div className="animate-fade-in"><Phone userId="maya" /></div>}
      </div>
      {t.status === "CONFIRMED" && phase === "done" && (
        <div className="animate-pop text-lg font-bold">Everyone is confirmed. Press Finish.</div>
      )}
    </div>
  );
}

function Done() {
  return (
    <main className="flex flex-1 animate-step flex-col items-center justify-center px-6 pb-24 text-center">
      <span className="grid size-20 animate-pop place-items-center rounded-full bg-lime text-lime-foreground"><Check className="size-10" /></span>
      <h1 className="mt-8 text-4xl font-semibold tracking-tight md:text-5xl">Trip confirmed</h1>
      <p className="mt-3 text-lg text-muted-foreground">Meijer, Saturday 2:04 PM in the Nissan Leaf. $7.50 per person.</p>
      <Link to="/profile" className="mt-10 rounded-full bg-primary px-8 py-4 font-bold text-primary-foreground transition hover:brightness-105 active:scale-[0.97]">Go to profile</Link>
      <Link to="/" className="mt-4 text-sm font-semibold text-muted-foreground underline underline-offset-4">Back to home</Link>
    </main>
  );
}
