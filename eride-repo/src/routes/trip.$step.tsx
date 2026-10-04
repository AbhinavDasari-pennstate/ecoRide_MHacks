import { useState, type FormEvent } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Check, Clock3, Leaf, MapPin, RefreshCw } from "lucide-react";
import {
  accountRequest,
  useAccountDashboard,
  useSession,
  type AccountTrip,
} from "@/lib/account-api";
import { AccountTripCard } from "@/components/AccountTripCard";
import { LiveLocation } from "@/components/LiveLocation";
import { campusDay, campusTime } from "@/lib/backend";

export const Route = createFileRoute("/trip/$step")({
  validateSearch: (search: Record<string, unknown>): { trip?: number | undefined } => {
    const trip = Number(search["trip"]);
    return Number.isSafeInteger(trip) && trip > 0 ? { trip } : {};
  },
  component: BookingFlow,
});

const PICKUPS = [
  { name: "Central campus · Michigan Union", lat: 42.275, lng: -83.7413 },
  { name: "North campus · Pierpont Commons", lat: 42.2919, lng: -83.7178 },
];
const DESTINATIONS = [
  { name: "Meijer (Ann Arbor-Saline Rd)", lat: 42.2394, lng: -83.766 },
  { name: "Michigan Union · Central campus", lat: 42.275, lng: -83.7413 },
];
function tomorrow() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function BookingFlow() {
  const { step } = Route.useParams();
  const { trip: tripId } = Route.useSearch();
  const navigate = useNavigate();
  const user = useSession().data?.user;
  const dashboard = useAccountDashboard(user?.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pickupIndex, setPickupIndex] = useState(0);
  const [destinationIndex, setDestinationIndex] = useState(0);
  const [date, setDate] = useState(tomorrow);
  const [time, setTime] = useState("14:00");
  const [role, setRole] = useState<"passenger" | "driver">("passenger");
  const [partySize, setPartySize] = useState(1);
  const trip = dashboard.data?.trips.find((row) => row.id === tripId && row.user_id === user?.id);
  const match = dashboard.data?.matches.find(
    (row) =>
      row.status !== "cancelled" &&
      row.members.some((member) => member.trip_id === trip?.id && member.status !== "cancelled"),
  );
  const me = match?.members.find(
    (member) => member.user_id === user?.id && member.trip_id === trip?.id,
  );
  const currentStep = step === "1" ? 1 : step === "3" || step === "done" ? 3 : 2;
  const go = (next: string, id = tripId) =>
    navigate({ to: "/trip/$step", params: { step: next }, search: id ? { trip: id } : {} });

  async function act(operation: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    await act(async () => {
      const departure = new Date(`${date}T${time}`);
      if (!Number.isFinite(departure.getTime()) || departure.getTime() <= Date.now())
        throw new Error("Choose a departure time in the future.");
      const pickup = PICKUPS[pickupIndex]!;
      const destination = DESTINATIONS[destinationIndex]!;
      if (pickup.lat === destination.lat && pickup.lng === destination.lng)
        throw new Error("Choose a destination different from your pickup point.");
      const result = await accountRequest<{ trip: AccountTrip }>("/trips", {
        method: "POST",
        body: {
          user_id: user.id,
          role,
          dest_name: destination.name,
          origin_lat: pickup.lat,
          origin_lng: pickup.lng,
          dest_lat: destination.lat,
          dest_lng: destination.lng,
          window_start: departure.toISOString(),
          window_end: new Date(departure.getTime() + 45 * 60_000).toISOString(),
          party_size: partySize,
          needs_vehicle: role === "driver",
          max_detour_mi: 2,
        },
      });
      await dashboard.refetch();
      await go("2", result.trip.id);
    });
  }
  async function refreshMatch() {
    if (!trip) return;
    await act(async () => {
      await accountRequest(`/trips/${trip.id}/plan`, { method: "POST" });
      await dashboard.refetch();
      setNotice("Your trip has been checked for available rides.");
    });
  }

  return (
    <main className="account-page pb-20">
      <div className="mb-8 flex items-center justify-between gap-4 text-sm">
        <Link to="/" className="account-muted inline-flex items-center gap-2">
          <ArrowLeft className="size-4" />
          Home
        </Link>
        <span className="account-muted">
          {currentStep === 1 ? "New trip" : `Trip #${tripId ?? "—"}`}
        </span>
      </div>
      <ol aria-label="Booking progress" className="mb-9 grid grid-cols-3 gap-3">
        {["Your trip", "Find a ride", "Confirm"].map((label, i) => (
          <li
            key={label}
            aria-current={currentStep === i + 1 ? "step" : undefined}
            className={`border-t-2 pt-3 text-xs font-semibold sm:text-sm ${currentStep >= i + 1 ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
          >
            <span className="mr-2">0{i + 1}</span>
            {label}
          </li>
        ))}
      </ol>
      <header className="mb-8 max-w-2xl">
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          {currentStep === 1
            ? "Where are we going?"
            : match?.status === "confirmed"
              ? "Ride confirmed."
              : currentStep === 2
                ? "Find a ride."
                : me?.status === "accepted"
                  ? "Your place is accepted."
                  : "Review your ride."}
        </h1>
        <p className="account-muted mt-4 text-lg">
          {currentStep === 1
            ? "Choose your pickup, destination, and departure time."
            : match?.status === "confirmed"
              ? "Your group and vehicle owner have confirmed the plan."
              : currentStep === 2
                ? "We'll look for people headed your way and a suitable shared vehicle."
                : "Your ride is confirmed once every traveler and the vehicle owner agree."}
        </p>
      </header>
      {error && (
        <p role="alert" className="account-error mb-5">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-5 rounded-xl bg-secondary p-4 text-sm">
          {notice}
        </p>
      )}
      {currentStep === 1 ? (
        <div className="grid items-start gap-6 lg:grid-cols-[1.35fr_.65fr]">
          <form onSubmit={(event) => void submit(event)} className="account-panel space-y-6">
            <div>
              <label className="account-label" htmlFor="trip-pickup">
                Pickup point
              </label>
              <select
                id="trip-pickup"
                className="account-input"
                value={pickupIndex}
                onChange={(event) => setPickupIndex(Number(event.target.value))}
              >
                {PICKUPS.map((pickup, i) => (
                  <option key={pickup.name} value={i}>
                    {pickup.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="account-label" htmlFor="trip-destination">
                Destination
              </label>
              <select
                id="trip-destination"
                className="account-input"
                value={destinationIndex}
                onChange={(event) => setDestinationIndex(Number(event.target.value))}
              >
                {DESTINATIONS.map((destination, i) => (
                  <option key={destination.name} value={i}>
                    {destination.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="account-label" htmlFor="trip-date">
                  Departure date
                </label>
                <input
                  id="trip-date"
                  className="account-input"
                  type="date"
                  required
                  value={date}
                  onChange={(event) => setDate(event.target.value)}
                />
              </div>
              <div>
                <label className="account-label" htmlFor="trip-time">
                  Departure time
                </label>
                <input
                  id="trip-time"
                  className="account-input"
                  type="time"
                  required
                  value={time}
                  onChange={(event) => setTime(event.target.value)}
                />
              </div>
            </div>
            <p className="account-muted !mt-2 text-xs">
              Times use your device's time zone. We look within 45 minutes of your departure.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="account-label" htmlFor="trip-role">
                  How would you like to travel?
                </label>
                <select
                  id="trip-role"
                  className="account-input"
                  value={role}
                  onChange={(event) => setRole(event.target.value as "passenger" | "driver")}
                >
                  <option value="passenger">I need a ride</option>
                  <option value="driver">I can drive a shared car</option>
                </select>
              </div>
              <div>
                <label className="account-label" htmlFor="trip-party">
                  People in your party
                </label>
                <input
                  id="trip-party"
                  className="account-input"
                  type="number"
                  min="1"
                  max="6"
                  required
                  value={partySize}
                  onChange={(event) => setPartySize(Number(event.target.value))}
                />
              </div>
            </div>
            <button
              className="account-button w-full justify-center"
              disabled={busy || !user}
              type="submit"
            >
              {busy ? "Saving your trip…" : "Find my ride"}
              <ArrowRight className="size-4" />
            </button>
          </form>
          <aside className="rounded-[1.75rem] bg-primary p-7 text-primary-foreground sm:p-8">
            <Leaf className="mb-10 size-8" />
            <h2 className="text-2xl font-semibold leading-tight">
              Trip costs.
              <br />
              CO₂ estimates.
            </h2>
            <p className="mt-4 text-sm leading-relaxed opacity-80">
              See the estimated cost and environmental savings before you confirm your place.
            </p>
            <div className="mt-8 border-t border-current/20 pt-5 text-sm">
              <MapPin className="mb-3 size-5" />
              Currently serving Ann Arbor campus pickup points.
            </div>
          </aside>
        </div>
      ) : dashboard.isPending ? (
        <p role="status" className="account-panel">
          Loading your trip…
        </p>
      ) : dashboard.error ? (
        <div className="account-panel">
          <p role="alert" className="account-error">
            {dashboard.error.message}
          </p>
          <button className="account-secondary mt-4" onClick={() => void dashboard.refetch()}>
            Try again
          </button>
        </div>
      ) : !trip ? (
        <div className="account-panel">
          <h2 className="text-xl font-semibold">This trip isn't in your account.</h2>
          <p className="account-muted mt-2">
            Choose a trip from your profile or start a new booking.
          </p>
          <Link to="/profile" className="account-button mt-5">
            My trips
          </Link>
        </div>
      ) : trip.status === "cancelled" ? (
        <div className="account-panel">
          <h2 className="text-xl font-semibold">This trip was cancelled.</h2>
          <button className="account-button mt-5" onClick={() => void go("1")}>
            Book another trip
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {currentStep === 3 && match?.status !== "confirmed" && (
            <button
              className="account-muted inline-flex items-center gap-2 text-sm"
              onClick={() => void go("2")}
            >
              <ArrowLeft className="size-4" />
              Back to ride options
            </button>
          )}
          <AccountTripCard trip={trip} match={match} />
          {!match ? (
            <section className="account-panel">
              <Clock3 className="mb-4 size-7 text-primary" />
              <h2 className="text-xl font-semibold">Your request is saved.</h2>
              <p className="account-muted mt-3 max-w-2xl">
                {trip.role === "passenger"
                  ? "We're waiting for a driver, vehicle, and compatible trips. Your request stays here while we look."
                  : "We're looking for a suitable shared vehicle and compatible travelers. Your request stays here while we look."}
              </p>
              <p className="account-muted mt-2 text-sm">
                This page updates automatically. You can also check back in My trips.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <button
                  disabled={busy}
                  className="account-button"
                  onClick={() => void refreshMatch()}
                >
                  <RefreshCw className="size-4" />
                  {busy ? "Checking…" : "Check for rides"}
                </button>
                <Link to="/profile" className="account-secondary">
                  My trips
                </Link>
              </div>
            </section>
          ) : (
            <>
              <section className="account-panel">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <h2 className="text-xl font-semibold">Your group</h2>
                  <span className="account-muted text-sm">
                    {match.pricing?.group_size ??
                      match.members.filter((m) => m.status !== "cancelled").length}{" "}
                    people
                  </span>
                </div>
                <ul className="divide-y divide-border">
                  {match.members
                    .filter((member) => member.status !== "cancelled")
                    .map((member) => (
                      <li key={member.trip_id} className="flex items-center gap-3 py-4">
                        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-secondary font-semibold">
                          {member.name.slice(0, 1)}
                        </span>
                        <div className="flex-1">
                          <span className="font-semibold">{member.name}</span>
                          {member.user_id === user?.id && (
                            <span className="account-muted ml-2 text-xs">You</span>
                          )}
                          <p className="account-muted text-xs">
                            {member.role === "driver" ? "Driver" : "Rider"}
                          </p>
                        </div>
                        <span className="text-xs font-medium">
                          {member.status === "accepted" ? "Accepted" : "Awaiting response"}
                        </span>
                      </li>
                    ))}
                </ul>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5">
                  <div>
                    <p className="font-semibold">{match.vehicle?.make_model ?? "Shared vehicle"}</p>
                    <p className="account-muted mt-1 text-sm">
                      {match.booking?.status === "approved"
                        ? "Owner approved"
                        : match.status === "at_risk"
                          ? "A replacement vehicle is needed"
                          : match.booking
                            ? "Waiting for the owner's approval"
                            : "No rental approval needed"}
                    </p>
                  </div>
                  {match.booking?.status === "approved" && (
                    <Check className="size-5 text-primary" />
                  )}
                </div>
                {match.reasons?.vehicle?.length ? (
                  <details className="mt-4 text-sm">
                    <summary className="cursor-pointer font-semibold">Why this car</summary>
                    <ul className="account-muted mt-2 list-disc space-y-1 pl-5">
                      {match.reasons.vehicle.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </section>
              {currentStep === 2 &&
                trip.role === "driver" &&
                (match.reasons?.vehicle_options?.length ?? 0) > 1 && (
                  <section className="account-panel">
                    <h2 className="text-xl font-semibold">Vehicle options</h2>
                    <p className="account-muted mt-2 text-sm">
                      Changing the vehicle asks everyone to review the new plan.
                    </p>
                    <div className="mt-5 grid gap-3 sm:grid-cols-2">
                      {match.reasons!.vehicle_options.map((option) => (
                        <div
                          key={option.vehicle_id}
                          className={`rounded-2xl border p-5 ${match.vehicle_id === option.vehicle_id ? "border-primary bg-secondary/40" : "border-border"}`}
                        >
                          <p className="font-semibold">
                            {option.make_model ??
                              (option.vehicle_id === match.vehicle?.id
                                ? match.vehicle.make_model
                                : `Shared vehicle #${option.vehicle_id}`)}
                          </p>
                          <p className="account-muted mt-2 text-sm">
                            ${(option.total_cost_cents / 100).toFixed(2)} estimated group total ·{" "}
                            {option.kg_co2.toFixed(1)} kg CO₂
                          </p>
                          {!option.feasible && (
                            <p className="mt-2 text-xs text-destructive">
                              {option.why_not.join("; ")}
                            </p>
                          )}
                          <button
                            disabled={
                              busy || !option.feasible || match.vehicle_id === option.vehicle_id
                            }
                            className="account-secondary mt-4"
                            onClick={() =>
                              void act(async () => {
                                await accountRequest(`/matches/${match.id}/vehicle`, {
                                  method: "POST",
                                  body: { vehicle_id: option.vehicle_id },
                                });
                                await dashboard.refetch();
                              })
                            }
                          >
                            {match.vehicle_id === option.vehicle_id ? "Selected" : "Choose vehicle"}
                          </button>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              {match.status === "at_risk" ? (
                <section className="account-panel">
                  <h2 className="text-xl font-semibold">The plan changed.</h2>
                  <p className="account-muted mt-2">
                    We'll need a suitable replacement before you can confirm.
                  </p>
                  <button
                    className="account-button mt-5"
                    disabled={busy}
                    onClick={() => void refreshMatch()}
                  >
                    Find a replacement
                  </button>
                </section>
              ) : currentStep === 2 ? (
                <div className="flex justify-end">
                  <button className="account-button" onClick={() => void go("3")}>
                    Review and confirm
                    <ArrowRight className="size-4" />
                  </button>
                </div>
              ) : (
                <section className="account-panel">
                  <h2 className="text-xl font-semibold">
                    {match.status === "confirmed"
                      ? "Trip confirmed"
                      : me?.status === "accepted"
                        ? "Waiting for your ride to be confirmed"
                        : "Ready to share the ride?"}
                  </h2>
                  <p className="account-muted mt-3">
                    {match.status === "confirmed"
                      ? `Your group departs on ${campusDay(match.depart_time)} at ${campusTime(match.depart_time)} (Ann Arbor time). ${trip.role === "passenger" ? "Confirm your pickup timing with the driver before departure." : "Coordinate pickup timing with your passengers before departure."}`
                      : me?.status === "accepted"
                        ? "You've accepted this plan. This page updates when the other travelers and vehicle owner respond."
                        : "Confirm only your place. The other travelers and the vehicle owner respond from their own accounts."}
                  </p>
                  <div className="mt-6 flex flex-wrap gap-3">
                    {me?.status === "pending" && (
                      <button
                        className="account-button"
                        disabled={busy}
                        onClick={() =>
                          void act(async () => {
                            await accountRequest(`/matches/${match.id}/accept`, {
                              method: "POST",
                              body: { user_id: user!.id },
                            });
                            await dashboard.refetch();
                            setNotice("Your acceptance is saved.");
                          })
                        }
                      >
                        {busy ? "Confirming…" : "Confirm my place"}
                        <Check className="size-4" />
                      </button>
                    )}
                    <Link to="/profile" className="account-secondary">
                      My trips
                    </Link>
                  </div>
                </section>
              )}
              {match.status === "confirmed" && user && (
                <LiveLocation
                  match={match}
                  userId={user.id}
                  travelRole={trip.role === "driver" ? "driver" : "passenger"}
                />
              )}
            </>
          )}
          <div className="border-t border-border pt-5">
            <button
              className="text-sm text-muted-foreground underline underline-offset-4 disabled:opacity-50"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await accountRequest(`/trips/${trip.id}/cancel`, { method: "POST" });
                  await dashboard.refetch();
                  setNotice("Your trip request has been cancelled.");
                })
              }
            >
              Cancel my trip request
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
