import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { BadgeCheck, RotateCcw } from "lucide-react";
import { useStore, userById } from "@/lib/store";
import { reset } from "@/lib/demo";
import { Avatar, Card, Eyebrow, RoleBadge, StatusPill } from "@/components/kit";
import { TripCard } from "@/components/TripCard";
import { CampusCard } from "@/components/Campus";

export const Route = createFileRoute("/profile")({
  head: () => ({
    meta: [
      { title: "Alex Rivera | ERIDE profile" },
      { name: "description", content: "Upcoming shared trips, vehicle listings, pending matches and campus impact." },
      { property: "og:title", content: "Alex Rivera | ERIDE profile" },
      { property: "og:description", content: "Upcoming shared trips, vehicle listings, pending matches and campus impact." },
    ],
  }),
  component: Profile,
});

function Profile() {
  const trips = useStore((s) => s.trips);
  const vehicles = useStore((s) => s.vehicles);
  const nav = useNavigate();
  const me = userById("alex");
  const pending = trips.flatMap((t) => t.participants.filter((p) => p.status === "PENDING").map((p) => ({ t, p })));
  const mine = vehicles.filter((v) => v.ownerId === "sam");
  return (
    <main className="mx-auto w-full max-w-6xl space-y-8 px-6 pb-20 pt-4 md:px-10">
      <header className="flex flex-wrap items-center gap-5">
        <Avatar id={me.id} size={76} />
        <div className="flex-1">
          <h1 className="text-3xl font-semibold tracking-tight">{me.name}</h1>
          <div className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground"><BadgeCheck className="size-4 text-green" />{me.edu} verified</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <RoleBadge role="Driver" /><RoleBadge role="Passenger" /><RoleBadge role="Owner" />
            {["Night drives", "Scenic routes"].map((p) => <span key={p} className="rounded-full border border-border px-2.5 py-0.5 text-xs font-medium">{p}</span>)}
          </div>
        </div>
      </header>

      <section className="space-y-5">
        <h2 className="text-lg font-bold">Upcoming trips</h2>
        {trips.map((t) => <TripCard key={t.id} t={t} />)}
      </section>

      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <h2 className="text-lg font-bold">My vehicle listings <span className="text-sm font-normal text-muted-foreground">(Sam, owner)</span></h2>
          <div className="mt-4 space-y-2">
            {mine.map((v) => (
              <div key={v.id} className="flex items-center justify-between text-sm"><span><b>{v.name}</b> · ${v.rate}/hr · {v.window}</span><StatusPill status={v.status} /></div>
            ))}
          </div>
        </Card>
        <Card>
          <h2 className="text-lg font-bold">Pending matches</h2>
          <div className="mt-4 space-y-2">
            {pending.length === 0 && <div className="text-sm text-muted-foreground">Nothing waiting on anyone.</div>}
            {pending.map(({ t, p }) => (
              <div key={t.id + p.userId} className="flex items-center gap-3"><Avatar id={p.userId} size={32} /><div className="flex-1 text-sm"><b>{userById(p.userId).name}</b> for {t.destination}</div><StatusPill status="PENDING" /></div>
            ))}
          </div>
        </Card>
      </div>

      <CampusCard />

      <div className="flex items-center justify-between border-t border-border pt-6">
        <Eyebrow>Shift + R resets from anywhere</Eyebrow>
        <button onClick={() => { reset(); nav({ to: "/" }); }} className="flex items-center gap-2 rounded-full border border-border px-4 py-2 text-sm font-semibold transition hover:bg-sand">
          <RotateCcw className="size-4" /> Reset demo
        </button>
      </div>
    </main>
  );
}
