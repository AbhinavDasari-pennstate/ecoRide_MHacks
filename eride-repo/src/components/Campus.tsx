import { useStore } from "@/lib/store";
import { Card } from "./kit";
export function CampusCard() {
  const c = useStore((s) => s.campus);
  const events = useStore((s) => s.events);
  return (
    <Card>
      <h2 className="text-lg font-bold">Campus impact and activity</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Projected savings across proposed and confirmed trips. Updated from the database.
      </p>
      <dl className="my-6 grid grid-cols-3 gap-4">
        {[
          ["kg CO2 avoided", c.kg],
          ["miles avoided", c.miles],
          ["trip requests shared", c.trips],
        ].map(([label, value]) => (
          <div key={label}>
            <dd className="text-2xl font-semibold text-green">{value}</dd>
            <dt className="text-xs text-muted-foreground">{label}</dt>
          </div>
        ))}
      </dl>
      <h3 className="font-semibold">Recent activity</h3>
      <ol className="mt-3 max-h-72 space-y-2 overflow-y-auto">
        {events
          .slice(-12)
          .reverse()
          .map((e) => (
            <li key={e.id} className="flex justify-between border-b border-border py-2 text-sm">
              <span>{e.kind.replaceAll("_", " ")}</span>
              <time className="text-muted-foreground">{new Date(e.ts).toLocaleTimeString()}</time>
            </li>
          ))}
      </ol>
      {!events.length && <p className="text-sm text-muted-foreground">No trip activity yet.</p>}
    </Card>
  );
}
