import type { ReactNode } from "react";
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
          <p className="account-muted mb-2 text-sm">
            {trip.role === "driver" ? "Driver" : "Rider"} · Trip #{trip.id}
          </p>
          <h2 className="text-2xl font-semibold tracking-tight">{trip.dest_name}</h2>
        </div>
        <span className="text-sm font-medium">{status}</span>
      </div>
      <div className="account-muted mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <span>
          {campusDay(match?.depart_time ?? trip.window_start)},{" "}
          {campusTime(match?.depart_time ?? trip.window_start)}
        </span>
        {match?.vehicle && <span>{match.vehicle.make_model}</span>}
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
              <p className="account-muted text-sm">Projected group CO₂ savings</p>
              <p className="mt-1 text-3xl font-semibold text-primary">
                {match.impact.kg_co2_avoided.toFixed(1)} <span className="text-base">kg</span>
              </p>
            </div>
          )}
        </div>
      ) : null}
      {match?.impact && (
        <p className="account-muted mt-4 text-xs">
          Compared with separate gasoline trips.{" "}
          {match.route?.source === "estimate"
            ? "Route distances are estimated."
            : "These are projected savings, not measured emissions."}
        </p>
      )}
      {children && <div className="mt-6 flex flex-wrap gap-3">{children}</div>}
    </article>
  );
}
