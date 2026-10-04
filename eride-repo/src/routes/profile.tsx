import { createFileRoute, Link } from "@tanstack/react-router";
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
          <h1>My trips</h1>
        </div>
        <Link
          className="account-button"
          to="/trip/$step"
          params={{ step: "1" }}
          search={{ trip: undefined }}
        >
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
        <p className="account-muted">No trips yet.</p>
      )}
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
                View trip
              </Link>
            </AccountTripCard>
          );
        })}
      </div>
    </main>
  );
}
