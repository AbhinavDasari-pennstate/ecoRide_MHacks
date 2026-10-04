import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { useStore } from "@/lib/store";
import { CountUp } from "@/components/kit";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ERIDE | Share the ride. Skip the extra trips." },
      { name: "description", content: "Campus carpooling that picks the lowest-emissions option for you." },
      { property: "og:title", content: "ERIDE | Share the ride. Skip the extra trips." },
      { property: "og:description", content: "Campus carpooling that picks the lowest-emissions option for you." },
    ],
  }),
  component: Home,
});

function Home() {
  const c = useStore((s) => s.campus);
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-6 pb-24 text-center">
      <h1 className="max-w-4xl animate-fade-in text-4xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
        Share the ride.<br />Skip the extra trips.
      </h1>
      <p className="mt-6 max-w-xl text-lg text-muted-foreground md:text-xl">Campus carpooling that picks the lowest-emissions option for you.</p>
      <Link
        to="/trip/$step"
        params={{ step: "1" }}
        className="group mt-12 inline-flex items-center gap-3 rounded-full bg-primary px-10 py-5 text-lg font-semibold text-primary-foreground transition duration-200 hover:-translate-y-0.5 hover:brightness-105 active:translate-y-0 active:scale-[0.97]"
      >
        Begin trip <ArrowRight className="size-5 transition group-hover:translate-x-1" />
      </Link>
      <dl className="mt-20 grid grid-cols-3 gap-8 text-muted-foreground md:gap-16">
        {[["kg CO2 avoided on campus", c.kg, true], ["miles avoided", c.miles, false], ["trips shared", c.trips, false]].map(([k, v, g]) => (
          <div key={k as string}>
            <dd className={`text-2xl font-semibold md:text-3xl ${g ? "text-green" : "text-primary"}`}><CountUp to={v as number} /></dd>
            <dt className="mt-1 text-xs uppercase tracking-widest">{k}</dt>
          </div>
        ))}
      </dl>
    </main>
  );
}
