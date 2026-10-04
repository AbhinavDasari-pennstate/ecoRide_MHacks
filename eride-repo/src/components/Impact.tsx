import { useMainTrip } from "@/lib/store";
import { CountUp } from "./kit";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
export function AssumptionsDrawer({ children }: { children: React.ReactNode }) {
  const trip = useMainTrip();
  return (
    <Sheet>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent className="z-[70] w-[440px] overflow-y-auto bg-card">
        <SheetHeader>
          <SheetTitle>Assumptions used for this trip</SheetTitle>
        </SheetHeader>
        <dl className="space-y-4 px-4 pb-8 text-sm">
          {Object.entries(trip?.assumptions ?? {}).map(([key, value]) => {
            const record =
              value && typeof value === "object"
                ? (value as { value?: number; unit?: string; source?: string; url?: string })
                : null;
            return (
              <div key={key} className="border-b border-border pb-4">
                <dt className="font-semibold">{key.replaceAll("_", " ")}</dt>
                <dd className="mt-1">
                  {record ? `${record.value ?? ""} ${record.unit ?? ""}` : String(value)}
                </dd>
                {record?.source && <p className="mt-1 text-muted-foreground">{record.source}</p>}
                {record?.url && (
                  <a className="underline" href={record.url} target="_blank" rel="noreferrer">
                    Source
                  </a>
                )}
              </div>
            );
          })}
        </dl>
      </SheetContent>
    </Sheet>
  );
}
export function ImpactSummary() {
  const t = useMainTrip();
  if (!t?.matchId) return <p>Match a trip to calculate its projected impact.</p>;
  const imp = t.impact;
  return (
    <div className="rounded-[2rem] border border-border bg-card p-8 shadow-float md:p-12">
      <div className="text-xs uppercase tracking-widest text-muted-foreground">
        Projected impact ?{" "}
        {t.distanceSource === "estimate" ? "estimated road distances" : t.distanceSource}
      </div>
      <h2 className="mt-3 text-3xl font-semibold md:text-5xl">
        {t.costs.people} people. One shared trip.
      </h2>
      <p className="mt-3 text-muted-foreground">
        Compared with separate gasoline round trips to {t.destination}.
      </p>
      <div className="mt-10 grid gap-8 md:grid-cols-3">
        {[
          ["CO2 avoided", imp.avoided, " kg"],
          ["Emissions reduction", imp.pct, "%"],
          ["Miles avoided", imp.milesAvoided, " mi"],
          ["CO2 if separate", imp.separate, " kg"],
          ["CO2 shared", imp.shared, " kg"],
        ].map(([label, value, suffix]) => (
          <div key={String(label)} className="border-t border-border pt-5">
            <div className="text-sm text-muted-foreground">{label}</div>
            <div className="mt-2 text-4xl font-semibold text-green">
              <CountUp to={Number(value)} decimals={2} suffix={String(suffix)} />
            </div>
          </div>
        ))}
        <div className="border-t border-border pt-5">
          <div className="text-sm text-muted-foreground">Estimated share including energy</div>
          <div className="mt-2 text-4xl font-semibold">
            <CountUp to={t.costs.perPerson} prefix="$" decimals={2} />
          </div>
          <p>
            ${t.costs.total.toFixed(2)} total for {t.costs.people} people
          </p>
        </div>
      </div>
      <AssumptionsDrawer>
        <button className="mt-8 rounded-full border border-primary px-5 py-3 font-semibold">
          See assumptions
        </button>
      </AssumptionsDrawer>
    </div>
  );
}
