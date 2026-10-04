import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight, Plus } from "lucide-react";
import { useAccountDashboard, useSession } from "@/lib/account-api";
import { AccountTripCard } from "@/components/AccountTripCard";
export const Route = createFileRoute("/profile")({
  head: () => ({ meta: [{ title: "My trips | ERIDE" }] }),
  component: Profile,
});
export function Profile() {
  const user = useSession().data?.user;
  const dashboard = useAccountDashboard(user?.id);
  const trips = dashboard.data?.trips ?? [];
  return (
    <main className="account-page">
      <div className="account-page-heading">
        <div>
          <p className="account-eyebrow">Your account</p>
          <h1>{user?.name.split(" ")[0]}'s trips</h1>
          <p className="account-muted">View and manage your trip requests.</p>
        </div>
        <Link
          className="account-button"
          to="/trip/$step"
          params={{ step: "1" }}
          search={{ trip: undefined }}
        >
          <Plus size={16} />
          Book a trip
        </Link>
      </div>
      {dashboard.isPending && (
        <p role="status" className="account-muted">
          Loading your trips…
        </p>
      )}
      {dashboard.error && (
        <div className="account-error" role="alert">
          {dashboard.error.message}
          <button className="ml-3 underline" onClick={() => void dashboard.refetch()}>
            Try again
          </button>
        </div>
      )}
      {!dashboard.isPending && !dashboard.error && !trips.length && (
        <div className="account-panel account-empty">
          <h2>Your first shared trip is waiting.</h2>
          <p className="account-muted">Pick a destination and we'll look for a match.</p>
          <Link
            className="account-secondary"
            to="/trip/$step"
            params={{ step: "1" }}
            search={{ trip: undefined }}
          >
            Book a trip <ArrowRight size={15} />
          </Link>
        </div>
      )}
      {dashboard.data?.impact?.trips ? (
        <section className="account-panel mb-5" aria-labelledby="profile-impact">
          <p className="account-eyebrow">Your impact</p>
          <h2 id="profile-impact" className="mt-1 text-xl font-semibold">
            Your share of the savings
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-3">
            {(
              [
                [dashboard.data.impact.kg_co2_avoided.toFixed(1), "kg CO₂ avoided"],
                [dashboard.data.impact.miles_avoided.toFixed(1), "car miles avoided"],
                [String(dashboard.data.impact.trips), "shared trips"],
              ] as [string, string][]
            ).map(([value, label]) => (
              <div key={label}>
                <p className="text-3xl font-semibold text-primary">{value}</p>
                <p className="account-muted text-sm">{label}</p>
              </div>
            ))}
          </div>
          <p className="account-muted mt-4 text-xs">
            About {dashboard.data.impact.equivalents.tree_seedlings_10yr} tree seedlings growing for
            ten years, or {dashboard.data.impact.equivalents.smartphone_charges.toLocaleString()} phone
            charges. {dashboard.data.impact.basis}.
          </p>
        </section>
      ) : null}
      <div className="grid gap-5">
        {trips.map((trip) => {
          const match =
            trip.status === "cancelled"
              ? undefined
              : dashboard.data?.matches.find(
                  (m) =>
                    m.status !== "cancelled" &&
                    m.members.some(
                      (member) => member.trip_id === trip.id && member.status !== "cancelled",
                    ),
                );
          return (
            <AccountTripCard key={trip.id} trip={trip} match={match}>
              <Link
                className="account-secondary"
                to="/trip/$step"
                params={{ step: "2" }}
                search={{ trip: trip.id }}
              >
                View trip <ArrowRight size={15} />
              </Link>
            </AccountTripCard>
          );
        })}
      </div>
    </main>
  );
}
