import { CountUp } from "./kit";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

export function AssumptionsDrawer({ children }: { children: React.ReactNode }) {
  return (
    <Sheet>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent className="z-[70] w-[420px] bg-card">
        <SheetHeader><SheetTitle className="text-2xl">Assumptions</SheetTitle></SheetHeader>
        <dl className="space-y-5 px-4 text-sm">
          {[
            ["Gas car emissions", "0.40 kg CO2 per mile"],
            ["EV emissions", "0.12 kg CO2 per mile"],
            ["Counterfactual", "Three separate solo trips by gas car, one per rider"],
            ["Round trip distance", "14.1 miles, campus to Meijer and back"],
            ["Shared trip", "One EV carrying all three riders, 14.1 miles"],
            ["Grid mix", "EV figure varies by grid mix. We use a regional Midwest average."],
          ].map(([k, v]) => (
            <div key={k} className="border-b border-border pb-4">
              <dt className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{k}</dt>
              <dd className="mt-1 text-base font-medium">{v}</dd>
            </div>
          ))}
        </dl>
      </SheetContent>
    </Sheet>
  );
}

export function ImpactSummary() {
  return (
    <div className="w-full rounded-[2rem] border border-border bg-card p-8 shadow-float md:p-12">
      <div className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">Impact summary</div>
      <h2 className="mt-3 text-3xl font-semibold tracking-tight md:text-5xl">3 people. 1 EV. 1 shared trip<span className="text-primary">.</span></h2>
      <p className="mt-3 text-xl text-muted-foreground">Instead of 3 separate trips to Meijer.</p>
      <div className="mt-10 grid gap-x-10 gap-y-6 md:grid-cols-3">
        <div className="border-t border-border pt-6 md:col-span-2">
          <div className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">CO2 avoided</div>
          <div className="mt-2 text-7xl font-semibold leading-none text-green md:text-[120px]"><CountUp to={15.2} decimals={1} /><span className="text-4xl md:text-5xl"> kg</span></div>
          <div className="mt-3 text-2xl font-bold">About <CountUp to={90} suffix="%" /> lower</div>
        </div>
        <div className="border-t border-border pt-6">
          <div className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">Vehicle miles avoided</div>
          <div className="mt-2 text-7xl font-semibold text-primary"><CountUp to={28.2} decimals={1} /></div>
          <div className="mt-2 text-sm text-muted-foreground">3 x 14.1 solo minus 14.1 shared</div>
        </div>
        {[
          ["CO2 if separate", 16.9, " kg", "Gas, 0.40 kg/mi"],
          ["CO2 shared EV", 1.7, " kg", "0.12 kg/mi"],
          ["Rental per person", 6.67, "", "$20 total, split 3 ways"],
        ].map(([k, v, s, sub], i) => (
          <div key={k as string} className="border-t border-border pt-6">
            <div className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">{k}</div>
            <div className={`mt-2 text-5xl font-semibold ${i < 2 ? "text-green" : ""}`}><CountUp to={v as number} decimals={i === 2 ? 2 : 1} prefix={i === 2 ? "$" : ""} suffix={s as string} /></div>
            <div className="mt-2 text-sm text-muted-foreground">{sub}</div>
          </div>
        ))}
      </div>
      <AssumptionsDrawer>
        <button className="mt-8 rounded-full border border-primary px-5 py-2.5 text-sm font-semibold text-primary transition hover:bg-primary hover:text-primary-foreground">See assumptions</button>
      </AssumptionsDrawer>
    </div>
  );
}
