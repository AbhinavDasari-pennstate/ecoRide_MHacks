import { Clock, MapPin } from "lucide-react";
import { useStore, impactFor, tripCost, userById, type Trip } from "@/lib/store";
import { Avatar, Card, CountUp, Eyebrow, RoleBadge, StatusPill } from "./kit";

export function TripCard({ t }: { t: Trip }) {
  const vehicles = useStore((s) => s.vehicles);
  const v = vehicles.find((x) => x.id === t.vehicleId);
  const cost = tripCost(t, vehicles);
  const imp = impactFor(t, vehicles);
  const busy = t.vehicleState === "LOST" || t.vehicleState === "REOPTIMIZING";
  return (
    <Card className="animate-fade-in text-left">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2"><Eyebrow>{t.title}</Eyebrow><StatusPill status={t.status} /></div>
          <h3 className="mt-2 text-3xl font-semibold tracking-tight">{t.destination}</h3>
          <div className="mt-1 flex flex-wrap gap-4 text-sm text-muted-foreground">
            <span className="flex items-center gap-1"><Clock className="size-4" />{t.day} {t.departure}</span>
            <span className="flex items-center gap-1"><MapPin className="size-4" />{t.roundTripMi} mi round trip</span>
          </div>
        </div>
        <div className="flex gap-3">
          <div className="px-2 py-1">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">CO2 saved</div>
            <div className="text-3xl font-semibold text-green"><CountUp to={imp.avoided} decimals={1} /> <span className="text-base">kg</span></div>
          </div>
          <div className="px-2 py-1">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Miles avoided</div>
            <div className="text-3xl font-semibold"><CountUp to={imp.milesAvoided} decimals={1} /></div>
          </div>
        </div>
      </div>
      <div className="mt-6 grid gap-6 md:grid-cols-[1.3fr_1fr]">
        <div>
          <Eyebrow>Pickup timeline</Eyebrow>
          <ol className="mt-3 space-y-3">
            {t.participants.map((p) => (
              <li key={p.userId} className="flex items-center gap-3 border-b border-border py-2.5">
                <span className="num w-16 text-sm font-bold">{p.pickup}</span>
                <Avatar id={p.userId} size={34} />
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{userById(p.userId).name}</div>
                  <div className="flex items-center gap-2"><RoleBadge role={p.role} />{p.matchPct && <span className="text-xs text-muted-foreground">{p.matchPct}% match</span>}</div>
                </div>
                <StatusPill status={p.status} />
              </li>
            ))}
            <li className="flex items-center gap-3 p-2.5 text-sm text-muted-foreground"><span className="num w-16 font-bold">{t.time}</span><MapPin className="size-4" /> Arrive {t.destination}</li>
          </ol>
        </div>
        <div className="space-y-4">
          <div className={`rounded-xl border p-4 transition ${t.vehicleState === "LOST" ? "border-destructive bg-destructive/5" : "border-border"}`}>
            <div className="flex items-center justify-between"><Eyebrow>Vehicle</Eyebrow><StatusPill status={t.vehicleState} /></div>
            {busy ? (
              <div className="mt-2 flex items-center gap-2 text-lg font-bold">
                {t.vehicleState === "REOPTIMIZING" && <span className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />}
                {t.vehicleState === "LOST" ? <span className="text-destructive">Owner cancelled the Tesla</span> : "Finding the next cleanest car..."}
              </div>
            ) : v ? (
              <div key={v.id} className="mt-2 animate-fade-in">
                <div className="text-lg font-bold">{v.name} <span className={`ml-1 rounded px-1.5 text-xs ${v.type === "EV" ? "bg-lime text-lime-foreground" : "bg-sand"}`}>{v.type}</span></div>
                <div className="text-sm text-muted-foreground">Owner {userById(v.ownerId).name} · ${v.rate}/hr · {t.window}</div>
              </div>
            ) : (
              <div className="mt-2 text-sm text-muted-foreground">Driver has no car. We'll match one.</div>
            )}
          </div>
          <div className="rounded-xl border border-border p-4">
            <Eyebrow>Price split</Eyebrow>
            <div className="mt-1 flex items-end justify-between">
              <div className="text-4xl font-semibold"><CountUp to={cost.perPerson} decimals={2} prefix="$" /></div>
              <div className="text-right text-sm text-muted-foreground">per person<br /><span className="num">${cost.total.toFixed(2)} total / {cost.people}</span></div>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
