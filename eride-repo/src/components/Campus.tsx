import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "./kit";

const WEEK = [
  { w: "Wk 1", kg: 182 }, { w: "Wk 2", kg: 240 }, { w: "Wk 3", kg: 221 }, { w: "Wk 4", kg: 310 },
  { w: "Wk 5", kg: 356 }, { w: "Wk 6", kg: 402 }, { w: "Wk 7", kg: 468 }, { w: "Wk 8", kg: 531 },
];
const DORMS = [["East Quad", 812], ["South Quad", 694], ["Baits II", 561], ["Mosher-Jordan", 447], ["North Quad", 396]] as const;

export function CampusCard() {
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Campus impact</h2>
        <span className="rounded-full border border-dashed border-border px-3 py-1 text-xs font-semibold text-muted-foreground">Seeded demo data</span>
      </div>
      <div className="mt-4 grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div>
          <div className="text-sm text-muted-foreground">kg CO2 avoided per week</div>
          <div className="mt-2 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={WEEK}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis dataKey="w" tickLine={false} axisLine={false} fontSize={12} />
                <YAxis tickLine={false} axisLine={false} fontSize={12} />
                <Tooltip cursor={{ fill: "var(--muted)" }} contentStyle={{ borderRadius: 12, border: "1px solid var(--border)" }} />
                <Bar dataKey="kg" fill="var(--green)" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div>
          <div className="text-sm text-muted-foreground">Dorm leaderboard</div>
          <ol className="mt-3 space-y-3">
            {DORMS.map(([d, kg], i) => (
              <li key={d} className="flex items-center gap-3">
                <span className="num w-5 font-bold text-muted-foreground">{i + 1}</span>
                <div className="flex-1">
                  <div className="flex justify-between text-sm font-semibold"><span>{d}</span><span className="num">{kg} kg</span></div>
                  <div className="mt-1 h-2 rounded-full bg-muted"><div className="h-2 rounded-full bg-green" style={{ width: `${(kg / 812) * 100}%` }} /></div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </Card>
  );
}
