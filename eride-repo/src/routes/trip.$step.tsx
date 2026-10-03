import { useEffect } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Check, ChevronRight, Fuel, Mic, X, Zap } from "lucide-react";
import { useMainTrip, useStore, userById, MAIN_TRIP } from "@/lib/store";
import * as api from "@/lib/api";
import * as d from "@/lib/demo";
import { Avatar, Card, Eyebrow, RouteMap, StatusPill } from "@/components/kit";
import { Phone } from "@/components/Phone";
import { ImpactSummary } from "@/components/Impact";
import { TripCard } from "@/components/TripCard";
import { cn } from "@/lib/utils";

const STEPS = [
  {
    label: "Trip request",
    title: "Tell ERIDE where you're headed.",
    sub: "Try the guided conversation. Your request is saved to the database.",
  },
  {
    label: "Matching",
    title: "Travel together.",
    sub: "Compatible travelers and feasible vehicles are selected by the backend.",
  },
  {
    label: "Vehicle selection",
    title: "Choose your shared vehicle.",
    sub: "Compare feasible options using the calculated route, price and emissions.",
  },
  {
    label: "Traveler confirmations",
    title: "Everyone gets a say.",
    sub: "Each acceptance updates the same trip record.",
  },
  {
    label: "Owner approval",
    title: "The owner approves the rental.",
    sub: "The trip confirms once all travelers and the current vehicle owner approve.",
  },
  {
    label: "Impact summary",
    title: "See the difference sharing makes.",
    sub: "Projected savings, calculated from this trip and its vehicle.",
  },
  {
    label: "Disruption",
    title: "Keep the group moving.",
    sub: "Cancel the vehicle to find a replacement. Everyone reviews the changed plan.",
  },
];
export const Route = createFileRoute("/trip/$step")({ component: Flow });
const button =
  "rounded-full bg-primary px-5 py-3 font-semibold text-primary-foreground disabled:opacity-40";

function Flow() {
  const { step } = Route.useParams();
  const nav = useNavigate();
  const n = step === "done" ? 8 : Math.min(7, Math.max(1, Number(step) || 1));
  const busy = useStore((s) => s.busy || s.ui.voiceBusy);
  const t = useMainTrip();
  const locked = busy || !t;
  const go = (k: number) =>
    nav({ to: "/trip/$step", params: { step: k >= 8 ? "done" : String(k) } });
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea,button,[role=dialog]")) return;
      if (e.code === "Space" && n === 1 && !t) {
        e.preventDefault();
        void api.perform(d.advanceVoice);
      } else if (e.key === "ArrowRight" && !locked && n < 8) void go(n + 1);
      else if (e.key === "ArrowLeft" && n > 1) void go(n - 1);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });
  if (n === 8) return <Done />;
  const s = STEPS[n - 1]!;
  return (
    <div className="flex flex-1 flex-col">
      <div className="px-6 md:px-10">
        <div className="flex justify-between text-sm">
          <span>
            Step {n} of 7: {s.label}
          </span>
          <Link to="/" className="flex gap-1">
            <X className="size-4" /> Exit
          </Link>
        </div>
        <div className="mt-2 h-1 rounded-full bg-muted">
          <div className="h-full rounded-full bg-green" style={{ width: `${(n / 7) * 100}%` }} />
        </div>
      </div>
      <main key={n} className="mx-auto w-full max-w-6xl flex-1 px-6 pb-32 pt-10 text-center">
        <h1 className="text-3xl font-semibold tracking-tight md:text-5xl">{s.title}</h1>
        <p className="mx-auto mt-3 max-w-xl text-lg text-muted-foreground">{s.sub}</p>
        <div className="mt-10">
          {n === 1 && <StepVoice />}
          {n === 2 && <StepMatching />}
          {n === 3 && <StepVehicles />}
          {n === 4 && <StepRider />}
          {n === 5 && <StepOwner />}
          {n === 6 && <ImpactSummary />}
          {n === 7 && <StepDisruption />}
        </div>
      </main>
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background/95">
        <div className="mx-auto flex max-w-6xl justify-between px-6 py-4">
          <button
            onClick={() => (n > 1 ? void go(n - 1) : void nav({ to: "/" }))}
            className="flex items-center gap-2 px-5"
          >
            <ArrowLeft className="size-4" /> Back
          </button>
          <button
            disabled={locked}
            onClick={() => void go(n + 1)}
            className={cn(button, "flex items-center gap-2")}
          >
            {n === 7 ? "View trip" : "Continue"}
            <ArrowRight className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
function StepVoice() {
  const step = useStore((s) => s.ui.voiceLine);
  const busy = useStore((s) => s.busy || s.ui.voiceBusy);
  const t = useMainTrip();
  return (
    <div className="mx-auto max-w-2xl space-y-5 text-left">
      <Card>
        <div className="flex items-center gap-3">
          <Mic />
          <div>
            <Eyebrow>Conversation simulation</Eyebrow>
            <h2 className="text-lg font-bold">ERIDE Assistant</h2>
          </div>
        </div>
        <div className="my-8 space-y-4">
          {d.SCRIPT.slice(0, step).map((l, i) => (
            <div key={i} className={l.who === "user" ? "text-right" : ""}>
              <span className="inline-block max-w-[90%] rounded-2xl bg-sand px-4 py-3">
                {l.text}
              </span>
            </div>
          ))}
        </div>
        {!t && (
          <button
            disabled={busy}
            onClick={() => void api.perform(d.advanceVoice)}
            className={cn(button, "flex items-center gap-2")}
          >
            {busy ? "Creating trip?" : "Next line"}
            <ChevronRight className="size-4" />
          </button>
        )}
        {t && (
          <div className="flex items-center gap-3 text-primary">
            <Check /> Saved: {t.destination}, {t.day} {t.departure}
          </div>
        )}
      </Card>
      {t && <TripCard t={t} />}
    </div>
  );
}
function StepMatching() {
  const t = useMainTrip();
  const busy = useStore((s) => s.busy);
  useEffect(() => {
    void api.perform(d.ensureMatches);
  }, []);
  return (
    <div className="grid gap-6 text-left lg:grid-cols-2">
      <div className="space-y-3">
        {t?.participants.map((p) => (
          <Card key={p.userId}>
            <div className="flex items-center gap-3">
              <Avatar id={p.userId} />
              <div className="flex-1">
                <b>{userById(p.userId).name}</b>
                <p>
                  {p.role}
                  {p.matchPct != null && ` ? ${p.matchPct}% match`}
                </p>
              </div>
              <StatusPill status={p.status} />
            </div>
          </Card>
        ))}
        <p className="text-muted-foreground">{t?.explanation ?? "Finding compatible trips?"}</p>
        <button
          disabled={busy}
          className={button}
          onClick={() => void api.perform(() => api.find_matches(MAIN_TRIP))}
        >
          Retry matching
        </button>
      </div>
      <Card>
        <RouteMap />
        <p className="mt-3 text-xs text-muted-foreground">
          {t?.distanceSource === "estimate"
            ? "Estimated route; no live road data"
            : "Pickup route from the backend"}
        </p>
      </Card>
    </div>
  );
}
function StepVehicles() {
  const t = useMainTrip();
  const vehicles = useStore((s) => s.vehicles);
  const busy = useStore((s) => s.busy);
  useEffect(() => {
    void api.perform(d.ensureVehicle);
  }, []);
  const candidates = t?.options ?? [];
  return (
    <div className="space-y-6 text-left">
      <div className="grid gap-6 md:grid-cols-2">
        {candidates.map((option) => {
          const v = vehicles.find((v) => Number(v.id) === option.vehicle_id);
          if (!v) return null;
          const on = t?.vehicleId === v.id;
          return (
            <Card key={v.id} className={on ? "ring-2 ring-primary" : ""}>
              <div className="flex justify-between">
                {v.type === "EV" ? <Zap /> : <Fuel />}
                <StatusPill
                  status={on ? "PENDING" : "AVAILABLE"}
                  label={on ? "SELECTED" : v.type}
                />
              </div>
              <h2 className="mt-4 text-2xl font-semibold">{v.name}</h2>
              <p className="text-muted-foreground">
                Owner {userById(v.ownerId).name} ? ${v.rate}/hr
              </p>
              <dl className="mt-5 grid grid-cols-3 gap-3">
                {[
                  ["Deadhead", `${option.deadhead_mi} mi`],
                  ["Trip cost", `$${(option.total_cost_cents / 100).toFixed(2)}`],
                  ["Trip CO2", `${option.kg_co2.toFixed(2)} kg`],
                ].map(([k, val]) => (
                  <div key={k}>
                    <dt className="text-xs text-muted-foreground">{k}</dt>
                    <dd className="text-xl font-bold">{val}</dd>
                  </div>
                ))}
              </dl>
              {!option.feasible && (
                <p className="mt-4 text-sm text-destructive">{option.why_not.join("; ")}</p>
              )}
              {!on && (
                <button
                  disabled={busy || !option.feasible}
                  className={cn(button, "mt-5")}
                  onClick={() => void api.perform(() => api.reserve_vehicle(MAIN_TRIP, v.id))}
                >
                  Choose {v.name}
                </button>
              )}
            </Card>
          );
        })}
      </div>
      {!candidates.length && <p>No feasible vehicle yet. Retry matching on the previous step.</p>}
      <p className="text-muted-foreground">{t?.explanation}</p>
    </div>
  );
}
function TravelerApprovals() {
  const t = useMainTrip();
  const busy = useStore((s) => s.busy);
  return (
    <div className="space-y-3">
      {t?.participants.map((p) => (
        <Card key={p.userId}>
          <div className="flex flex-wrap items-center gap-3">
            <Avatar id={p.userId} />
            <b className="flex-1">{userById(p.userId).name}</b>
            <StatusPill status={p.status} />
            {p.status === "PENDING" && (
              <button
                className={button}
                disabled={busy}
                onClick={() => void api.perform(() => api.accept_match(MAIN_TRIP, p.userId))}
              >
                Accept for {userById(p.userId).name}
              </button>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}
function StepRider() {
  const t = useMainTrip();
  useEffect(() => {
    void api.perform(d.step4);
  }, [t?.matchId, t?.vehicleId]);
  return (
    <div className="grid gap-8 text-left md:grid-cols-2">
      <TravelerApprovals />
      <Phone userId="maya" />
    </div>
  );
}
function OwnerApproval() {
  const t = useMainTrip();
  const vehicles = useStore((s) => s.vehicles);
  const bookings = useStore((s) => s.bookings);
  const busy = useStore((s) => s.busy);
  const v = vehicles.find((v) => v.id === t?.vehicleId);
  const b = bookings.find((b) => b.tripId === MAIN_TRIP);
  if (!v || !b) return <p>No vehicle reservation yet.</p>;
  return (
    <Card>
      <h2 className="text-xl font-bold">{v.name}</h2>
      <p>Owner: {userById(v.ownerId).name}</p>
      <p className="my-3">
        {b.window} ? ${b.amount.toFixed(2)} rental
      </p>
      <StatusPill status={b.status} />
      {b.status === "PENDING" && (
        <div className="mt-4 flex gap-3">
          <button
            disabled={busy}
            className={button}
            onClick={() => void api.perform(() => api.respond_booking(b.id, true))}
          >
            Approve as {userById(v.ownerId).name}
          </button>
          <button
            disabled={busy}
            className="px-4 underline"
            onClick={() => void api.perform(() => api.respond_booking(b.id, false))}
          >
            Decline
          </button>
        </div>
      )}
    </Card>
  );
}
function StepOwner() {
  const t = useMainTrip();
  const owner = useStore((s) => s.vehicles.find((v) => v.id === t?.vehicleId)?.ownerId);
  useEffect(() => {
    void api.perform(d.step5);
  }, [t?.matchId, t?.vehicleId]);
  return (
    <div className="grid gap-8 text-left md:grid-cols-2">
      <OwnerApproval />
      {owner && <Phone userId={owner} />}
    </div>
  );
}
function StepDisruption() {
  const t = useMainTrip();
  const busy = useStore((s) => s.busy);
  const phase = useStore((s) => s.ui.disruption);
  if (!t) return <p>Create a trip first.</p>;
  return (
    <div className="space-y-6 text-left">
      <button
        disabled={busy || phase === "running" || !t.vehicleId}
        className="rounded-full border-2 border-destructive px-6 py-3 font-bold text-destructive disabled:opacity-40"
        onClick={() => void api.perform(d.simulateCancellation)}
      >
        {phase === "running" ? "Finding a replacement?" : "Simulate vehicle cancellation"}
      </button>
      <TripCard t={t} />
      {t.vehicleState === "LOST" && (
        <button
          className={button}
          disabled={busy}
          onClick={() => void api.perform(() => api.find_matches(MAIN_TRIP))}
        >
          Retry replacement
        </button>
      )}
      {(phase === "done" || t.changed) && (
        <>
          <h2 className="text-xl font-bold">Review the replacement</h2>
          <TravelerApprovals />
          <OwnerApproval />
        </>
      )}
    </div>
  );
}
function Done() {
  const t = useMainTrip();
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 p-6 pb-20 text-center">
      <h1 className="text-4xl font-semibold">
        {t?.status === "CONFIRMED" ? "Trip confirmed" : "Your trip is saved"}
      </h1>
      <p className="text-muted-foreground">
        {t?.status === "CONFIRMED"
          ? "Every traveler and the vehicle owner have approved."
          : "The trip is awaiting the remaining confirmations."}
      </p>
      {t && <TripCard t={t} />}
      <Link to="/profile" className={cn(button, "inline-block")}>
        Go to profile
      </Link>
    </main>
  );
}
