import { useState, type FormEvent } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { accountRequest, useAccountDashboard, useSession } from "@/lib/account-api";
import { campusDay, windowLabel } from "@/lib/backend";

export const Route = createFileRoute("/owner")({ component: OwnerPage });

function nextDayTime(hour: string) {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${hour}:00`;
}

export function OwnerPage() {
  const user = useSession().data?.user;
  const dashboard = useAccountDashboard(user?.id);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [model, setModel] = useState("");
  const [fuel, setFuel] = useState<"ev" | "gas">("ev");
  const [seats, setSeats] = useState(5);
  const [range, setRange] = useState(250);
  const [efficiency, setEfficiency] = useState(0.27);
  const [rate, setRate] = useState(8);
  const [start, setStart] = useState(() => nextDayTime("08"));
  const [end, setEnd] = useState(() => nextDayTime("22"));
  const [pickup, setPickup] = useState("central");
  const vehicles = (dashboard.data?.vehicles ?? []).filter(
    (vehicle) => vehicle.owner_id === user?.id,
  );
  const bookings = (dashboard.data?.matches ?? []).filter(
    (match) =>
      match.status !== "cancelled" &&
      match.vehicle?.owner_id === user?.id &&
      match.booking &&
      ["requested", "approved"].includes(match.booking.status),
  );

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
  async function addVehicle(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    await act(async () => {
      const begins = new Date(start),
        ends = new Date(end);
      if (
        !Number.isFinite(begins.getTime()) ||
        !Number.isFinite(ends.getTime()) ||
        begins.getTime() <= Date.now() ||
        ends <= begins
      )
        throw new Error("Choose a future availability window with an end after the start.");
      await accountRequest("/vehicles", {
        method: "POST",
        body: {
          owner_id: user.id,
          make_model: model.trim(),
          fuel_type: fuel,
          seats,
          range_mi: range,
          efficiency,
          price_per_hour_cents: Math.round(rate * 100),
          avail_start: begins.toISOString(),
          avail_end: ends.toISOString(),
          lat: pickup === "central" ? 42.275 : 42.2919,
          lng: pickup === "central" ? -83.7413 : -83.7178,
        },
      });
      await dashboard.refetch();
      setShowForm(false);
      setModel("");
      setNotice("Vehicle listed.");
    });
  }

  return (
    <main className="account-page space-y-9 pb-20">
      <header className="account-page-heading">
        <h1>My cars</h1>
        <button
          className="account-button"
          onClick={() => setShowForm(!showForm)}
          aria-expanded={showForm}
        >
          {showForm ? "Close form" : "List a vehicle"}
        </button>
      </header>
      {error && (
        <p role="alert" className="account-error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-xl bg-secondary p-4 text-sm">
          {notice}
        </p>
      )}
      {showForm && (
        <form onSubmit={(event) => void addVehicle(event)} className="account-panel space-y-5">
          <h2 className="text-2xl font-semibold">List your vehicle</h2>
          <div className="grid gap-5 md:grid-cols-2">
            <div>
              <label className="account-label" htmlFor="vehicle-model">
                Make and model
              </label>
              <input
                id="vehicle-model"
                className="account-input"
                required
                maxLength={120}
                placeholder="e.g. Nissan Leaf"
                value={model}
                onChange={(event) => setModel(event.target.value)}
              />
            </div>
            <div>
              <label className="account-label" htmlFor="vehicle-fuel">
                Vehicle type
              </label>
              <select
                id="vehicle-fuel"
                className="account-input"
                value={fuel}
                onChange={(event) => {
                  const value = event.target.value as "ev" | "gas";
                  setFuel(value);
                  setEfficiency(value === "ev" ? 0.27 : 32);
                }}
              >
                <option value="ev">Electric</option>
                <option value="gas">Gasoline</option>
              </select>
            </div>
            <div>
              <label className="account-label" htmlFor="vehicle-seats">
                Seats, including driver
              </label>
              <input
                id="vehicle-seats"
                className="account-input"
                type="number"
                required
                min="2"
                max="8"
                value={seats}
                onChange={(event) => setSeats(Number(event.target.value))}
              />
            </div>
            <div>
              <label className="account-label" htmlFor="vehicle-rate">
                Rental price per hour ($)
              </label>
              <input
                id="vehicle-rate"
                className="account-input"
                type="number"
                required
                min="0"
                max="500"
                step="0.01"
                value={rate}
                onChange={(event) => setRate(Number(event.target.value))}
              />
            </div>
            <div>
              <label className="account-label" htmlFor="vehicle-range">
                Available driving range (miles)
              </label>
              <input
                id="vehicle-range"
                className="account-input"
                type="number"
                required
                min="1"
                max="1000"
                value={range}
                onChange={(event) => setRange(Number(event.target.value))}
              />
            </div>
            <div>
              <label className="account-label" htmlFor="vehicle-efficiency">
                {fuel === "ev" ? "Energy use (kWh per mile)" : "Fuel economy (miles per gallon)"}
              </label>
              <input
                id="vehicle-efficiency"
                className="account-input"
                type="number"
                required
                min={fuel === "ev" ? "0.01" : "1"}
                max={fuel === "ev" ? "2" : "150"}
                step={fuel === "ev" ? "0.001" : "0.1"}
                value={efficiency}
                onChange={(event) => setEfficiency(Number(event.target.value))}
              />
            </div>
            <div>
              <label className="account-label" htmlFor="vehicle-start">
                Available from
              </label>
              <input
                id="vehicle-start"
                className="account-input"
                type="datetime-local"
                required
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </div>
            <div>
              <label className="account-label" htmlFor="vehicle-end">
                Available until
              </label>
              <input
                id="vehicle-end"
                className="account-input"
                type="datetime-local"
                required
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </div>
            <div className="md:col-span-2">
              <label className="account-label" htmlFor="vehicle-pickup">
                Vehicle pickup point
              </label>
              <select
                id="vehicle-pickup"
                className="account-input"
                value={pickup}
                onChange={(event) => setPickup(event.target.value)}
              >
                <option value="central">Central campus · Michigan Union</option>
                <option value="north">North campus · Pierpont Commons</option>
              </select>
            </div>
          </div>
          <p className="account-muted text-xs">
            Times use your device's time zone. Check the default range and efficiency against your
            car.
          </p>
          <button className="account-button" disabled={busy || !user} type="submit">
            {busy ? "Saving listing…" : "Publish listing"}
          </button>
        </form>
      )}
      {dashboard.isPending ? (
        <p role="status" className="account-panel">
          Loading your vehicles…
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
      ) : (
        <>
          <section>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-xl font-semibold">Booking requests</h2>
              <span className="account-muted text-sm">
                {bookings.filter((match) => match.booking?.status === "requested").length} awaiting
                your reply
              </span>
            </div>
            {bookings.length === 0 ? (
              <p className="account-muted text-sm">No booking requests.</p>
            ) : (
              <div className="grid gap-5 md:grid-cols-2">
                {bookings.map((match) => {
                  const booking = match.booking!;
                  return (
                    <article key={booking.id} className="account-panel">
                      <div className="flex items-start justify-between gap-3">
                        <h3 className="text-xl font-semibold">{match.vehicle!.make_model}</h3>
                        <span className="text-sm font-medium">
                          {booking.status === "approved" ? "Approved" : "Needs your approval"}
                        </span>
                      </div>
                      <p className="account-muted mt-3 text-sm">
                        {campusDay(booking.start_ts)} ·{" "}
                        {windowLabel(booking.start_ts, booking.end_ts)}
                      </p>
                      <p className="account-muted mt-3 text-sm">
                        Travelers:{" "}
                        {match.members
                          .filter((member) => member.status !== "cancelled")
                          .map((member) => member.name)
                          .join(", ")}
                      </p>
                      <div className="mt-5 border-t border-border pt-4">
                        <p className="account-muted text-xs">Estimated rental amount</p>
                        <p className="mt-1 text-3xl font-semibold">
                          ${(booking.price_cents / 100).toFixed(2)}
                        </p>
                      </div>
                      {booking.status === "requested" ? (
                        <div className="mt-5 flex flex-wrap gap-3">
                          <button
                            className="account-button"
                            disabled={busy}
                            onClick={() =>
                              void act(async () => {
                                await accountRequest(`/bookings/${booking.id}/approve`, {
                                  method: "POST",
                                });
                                await dashboard.refetch();
                                setNotice("Booking approved.");
                              })
                            }
                          >
                            Approve request
                          </button>
                          <button
                            className="account-secondary"
                            disabled={busy}
                            onClick={() =>
                              void act(async () => {
                                await accountRequest(`/bookings/${booking.id}/decline`, {
                                  method: "POST",
                                });
                                await dashboard.refetch();
                                setNotice("Booking declined.");
                              })
                            }
                          >
                            Decline
                          </button>
                        </div>
                      ) : (
                        <p className="mt-5 text-sm text-primary">
                          {match.status === "confirmed"
                            ? "The trip is confirmed."
                            : "Waiting for the travelers to confirm."}
                        </p>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
          <section>
            <h2 className="mb-5 text-xl font-semibold">Your vehicles</h2>
            {vehicles.length === 0 ? (
              <p className="account-muted text-sm">No vehicles listed.</p>
            ) : (
              <div className="grid gap-5 md:grid-cols-2">
                {vehicles.map((vehicle) => (
                  <article key={vehicle.id} className="account-panel">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-xl font-semibold">{vehicle.make_model}</h3>
                      <span className="account-muted text-xs">
                        {vehicle.active ? "Listed" : "Removed"}
                      </span>
                    </div>
                    <p className="account-muted mt-2 text-sm">
                      {vehicle.seats} seats · {vehicle.fuel_type === "ev" ? "Electric" : "Gasoline"}{" "}
                      · ${(vehicle.price_per_hour_cents / 100).toFixed(2)}/hour
                    </p>
                    <p className="account-muted mt-2 text-sm">
                      {campusDay(vehicle.avail_start)}{" "}
                      {windowLabel(vehicle.avail_start, vehicle.avail_end)}
                    </p>
                    {vehicle.active && (
                      <div className="mt-5 border-t border-border pt-4">
                        <button
                          disabled={busy}
                          className="text-sm text-muted-foreground underline underline-offset-4 disabled:opacity-50"
                          onClick={() =>
                            void act(async () => {
                              await accountRequest(`/vehicles/${vehicle.id}/cancel`, {
                                method: "POST",
                              });
                              await dashboard.refetch();
                              setNotice("Listing removed. Its reservations have been cancelled.");
                            })
                          }
                        >
                          Remove listing
                        </button>
                        <p className="account-muted mt-2 text-xs">
                          Also cancels this vehicle's current reservations.
                        </p>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
