import type { ReactNode } from "react";
import { Car, Clock3, Leaf, MapPin } from "lucide-react";
import type { AccountTrip } from "@/lib/account-api";
import { campusDay, campusTime, type ApiMatch } from "@/lib/backend";

export function AccountTripCard({
  trip,
  match,
  children,
}: {
  trip: AccountTrip;
  match: ApiMatch | undefined;
  children?: ReactNode;
}) {
  const status =
    trip.status === "cancelled"
      ? "Cancelled"
      : match?.status === "confirmed"
        ? "Confirmed"
        : match?.status === "at_risk"
          ? "Finding a replacement"
          : match
            ? "Waiting for confirmations"
            : "Finding your group";
  return (
    <article className="account-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="account-muted mb-2 text-xs uppercase tracking-[.16em]">
            {trip.role === "driver" ? "Driving a shared trip" : "Your shared ride"}
          </p>
          <h2 className="text-2xl font-semibold tracking-tight">{trip.dest_name}</h2>
        </div>
        <span className="rounded-full bg-secondary px-3 py-1.5 text-xs font-semibold">
          {status}
        </span>
      </div>
      <div className="account-muted mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <span className="flex items-center gap-2">
          <Clock3 className="size-4" />
          {campusDay(match?.depart_time ?? trip.window_start)},{" "}
          {campusTime(match?.depart_time ?? trip.window_start)}
        </span>
        <span className="flex items-center gap-2">
          <MapPin className="size-4" />
          Ann Arbor
        </span>
        {match?.vehicle && (
          <span className="flex items-center gap-2">
            <Car className="size-4" />
            {match.vehicle.make_model}
          </span>
        )}
      </div>
      {match?.cost_per_person_cents != null ? (
        <div className="mt-6 grid gap-5 border-t border-border pt-5 sm:grid-cols-2">
          <div>
            <p className="account-muted text-sm">Estimated cost per person</p>
            <p className="mt-1 text-3xl font-semibold">
              ${(match.cost_per_person_cents / 100).toFixed(2)}
            </p>
          </div>
          {match.impact && (
            <div>
              <p className="account-muted flex items-center gap-1.5 text-sm">
                <Leaf className="size-4" />
                Projected group CO₂ savings
              </p>
              <p className="mt-1 text-3xl font-semibold text-primary">
                {match.impact.kg_co2_avoided.toFixed(1)} <span className="text-base">kg</span>
              </p>
              <p className="account-muted mt-1 text-xs">
                {match.impact.percent_reduction.toFixed(0)}% less than driving separately
              </p>
            </div>
          )}
        </div>
      ) : (
        <p className="account-muted mt-5 text-sm">
          {trip.status === "cancelled"
            ? "This request is no longer looking for a ride."
            : "Price and projected savings appear when a suitable ride is found."}
        </p>
      )}
      {match?.explanation && (
        <p className="mt-5 text-sm leading-relaxed">{match.explanation}</p>
      )}
      {match?.impact && (
        <p className="account-muted mt-4 text-xs">
          Compared with separate gasoline trips.{" "}
          {match.route?.source === "estimate"
            ? "Route distances are estimated."
            : "These are projected savings, not measured emissions."}
        </p>
      )}
      {match?.status === "confirmed" && (
        <p className="account-muted mt-2 text-xs">
          This confirmed ride also sends one simulated telemetry trip to the data portal. The demo
          data programme pays the car owner, so the fare above is what you pay and is unchanged.
        </p>
      )}
      {children && <div className="mt-6 flex flex-wrap gap-3">{children}</div>}
    </article>
  );
}
