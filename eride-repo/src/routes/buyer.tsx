import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
  ArrowDownToLine,
  ArrowRight,
  ChevronRight,
  CornerUpRight,
  MoveDownRight,
  X,
  Zap,
} from "lucide-react";
import { accountRequest, useSession } from "@/lib/account-api";

type Sample = typeof import("@/lib/buyerData");
export type BuyerDataset = Pick<
  Sample,
  "datasetSummary" | "demoTrips" | "driverSummaries" | "drivingEvents" | "eventLabels"
>;

export const Route = createFileRoute("/buyer")({
  head: () => ({
    meta: [
      { title: "Data Portal | ERIDE" },
      {
        name: "description",
        content: "Explore simulated driving patterns from one shared car and six drivers.",
      },
    ],
  }),
  component: BuyerPage,
});

function BuyerPage() {
  const { data: session } = useSession();
  const dataset = useQuery({
    queryKey: ["buyer", session?.user?.id],
    queryFn: () => accountRequest<BuyerDataset>("/buyer/dataset"),
    enabled: session?.user?.role === "buyer",
    retry: false,
  });
  if (dataset.isPending)
    return (
      <main className="account-page" role="status">
        Loading your data portal…
      </main>
    );
  if (dataset.error)
    return (
      <main className="account-page">
        <div className="account-panel">
          <h1>Couldn't load your data</h1>
          <p role="alert" className="account-error">
            {dataset.error.message}
          </p>
          <button className="account-button" onClick={() => void dataset.refetch()}>
            Try again
          </button>
        </div>
      </main>
    );
  return <BuyerPortal data={dataset.data} />;
}

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const date = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "America/Detroit",
});
const time = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "America/Detroit",
});
const eventIcons = {
  hard_brake: MoveDownRight,
  rapid_acceleration: Zap,
  sharp_turn: CornerUpRight,
};

function downloadSample(data: BuyerDataset) {
  const report = {
    simulated: true,
    description:
      "Synthetic demonstration data. Energy is estimated. Event flags use illustrative thresholds, not a validated risk model.",
    dataset: data.datasetSummary,
    trips: data.demoTrips,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "eride-simulated-trips.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function BuyerPortal({ data }: { data: BuyerDataset }) {
  const { datasetSummary, demoTrips, driverSummaries, drivingEvents, eventLabels } = data;
  const [metric, setMetric] = useState<"braking" | "energy">("braking");
  const [driver, setDriver] = useState<string | null>(null);
  const [eventType, setEventType] = useState("all");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(
    drivingEvents[0]?.id ?? null,
  );
  const visibleEvents = drivingEvents.filter(
    (event) =>
      (!driver || event.driverId === driver) && (eventType === "all" || event.type === eventType),
  );
  const selectedEvent =
    visibleEvents.find((event) => event.id === selectedEventId) ?? visibleEvents[0];
  const selectedTrip = selectedEvent
    ? demoTrips.find((trip) => trip.id === selectedEvent.tripId)
    : undefined;
  const value = (item: (typeof driverSummaries)[number]) =>
    metric === "braking" ? item.hardBrakesPer100Miles : item.energyPer100Miles;
  const maxValue = Math.max(1, ...driverSummaries.map(value));
  return (
    <main className="buyer-page">
      <header className="buyer-header">
        <div>
          <h1>Data Portal</h1>
          <p>
            {datasetSummary.vehicle} · {datasetSummary.driverCount} drivers ·{" "}
            {datasetSummary.tripCount} trips · {number.format(datasetSummary.miles)} miles ·{" "}
            {datasetSummary.eventCount} flagged events
          </p>
          <p>
            <strong>Simulated data</strong> · Energy estimates and illustrative event thresholds.{" "}
            {date.formatRange(
              new Date(`${datasetSummary.startDate}T12:00:00Z`),
              new Date(`${datasetSummary.endDate}T12:00:00Z`),
            )}{" "}
            · Ann Arbor time.
          </p>
        </div>
        <button className="buyer-download" onClick={() => downloadSample(data)}>
          <ArrowDownToLine size={16} /> Download JSON
        </button>
      </header>
      <div className="buyer-analysis-grid">
        <section className="buyer-panel buyer-comparison" aria-labelledby="comparison-title">
          <div className="buyer-panel-heading">
            <div>
              <h2 id="comparison-title">Compare drivers</h2>
              <p>Select a driver to filter events.</p>
            </div>
          </div>
          <div className="buyer-metric-switch" aria-label="Comparison metric">
            <button aria-pressed={metric === "braking"} onClick={() => setMetric("braking")}>
              Hard braking
            </button>
            <button aria-pressed={metric === "energy"} onClick={() => setMetric("energy")}>
              Estimated energy
            </button>
          </div>
          <p className="buyer-chart-unit">
            {metric === "braking"
              ? "Hard brakes per 100 miles · lower is fewer events"
              : "kWh per 100 miles · lower is less energy"}
          </p>
          <div className="buyer-bars">
            {driverSummaries.map((item) => (
              <button
                key={item.id}
                className={`buyer-bar-row ${driver === item.id ? "is-selected" : ""}`}
                aria-label={`Compare driver ${item.id}`}
                aria-describedby={`driver-${item.id}-description`}
                aria-pressed={driver === item.id}
                onClick={() => {
                  setDriver(driver === item.id ? null : item.id);
                  setSelectedEventId(null);
                }}
              >
                <span id={`driver-${item.id}-description`} className="sr-only">
                  {item.trips} trips, {item.miles} miles. {value(item).toFixed(1)}{" "}
                  {metric === "braking" ? "hard brakes" : "estimated kilowatt hours"} per 100 miles.
                </span>
                <span className="buyer-driver-avatar">{item.id}</span>
                <span className="buyer-bar-body">
                  <span className="buyer-bar-meta">
                    <span>
                      {item.trips} trips <span>· {number.format(item.miles)} mi</span>
                    </span>
                  </span>
                  <span className="buyer-bar-track">
                    <span
                      className="buyer-bar-fill"
                      style={{ width: `${(value(item) / maxValue) * 100}%` }}
                    />
                  </span>
                </span>
                <strong>{value(item).toFixed(1)}</strong>
                <ChevronRight size={14} className="buyer-bar-chevron" />
              </button>
            ))}
          </div>
        </section>

        <section className="buyer-panel buyer-feed" aria-label="Flagged events">
          <div className="buyer-panel-heading">
            <div>
              <h2>Flagged events</h2>
              <p>
                {visibleEvents.length} events <span>· {driver ?? "All drivers"}</span>
              </p>
            </div>
          </div>
          <div className="buyer-feed-controls">
            <label className="buyer-select">
              <span className="sr-only">Event type</span>
              <select
                value={eventType}
                onChange={(e) => {
                  setEventType(e.target.value);
                  setSelectedEventId(null);
                }}
              >
                <option value="all">All event types</option>
                {Object.entries(eventLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {driver && (
              <button
                className="buyer-clear"
                aria-label="Show all drivers"
                onClick={() => {
                  setDriver(null);
                  setSelectedEventId(null);
                }}
              >
                {driver}
                <X size={13} />
              </button>
            )}
          </div>
          <div className="buyer-event-list">
            {visibleEvents.length === 0 && (
              <div className="buyer-empty">
                <h3>No matching events</h3>
                <p>Try another event type or driver.</p>
                <button
                  onClick={() => {
                    setDriver(null);
                    setEventType("all");
                  }}
                >
                  Clear filters
                </button>
              </div>
            )}
            {visibleEvents.map((event) => {
              const Icon = eventIcons[event.type];
              return (
                <button
                  key={event.id}
                  className={`buyer-event ${selectedEvent?.id === event.id ? "is-selected" : ""}`}
                  aria-label={`Inspect ${eventLabels[event.type]} for ${event.driverId} on ${event.tripId}`}
                  aria-pressed={selectedEvent?.id === event.id}
                  onClick={() => setSelectedEventId(event.id)}
                >
                  <span
                    className={`buyer-event-icon ${event.severity === "Review" ? "is-review" : ""}`}
                  >
                    <Icon size={18} />
                  </span>
                  <span className="buyer-event-copy">
                    <strong>{eventLabels[event.type]}</strong>
                    <span>
                      {event.driverId} · {date.format(new Date(event.timestamp))} ·{" "}
                      {time.format(new Date(event.timestamp))}
                    </span>
                  </span>
                  <span
                    className={`buyer-severity ${event.severity === "Review" ? "is-review" : ""}`}
                  >
                    {event.severity}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      </div>

      <section className="buyer-panel buyer-detail" aria-label="Trip details">
        <div className="buyer-panel-heading">
          <div>
            <h2>Trip details</h2>
          </div>
          <span className="buyer-muted">{selectedTrip?.id ?? "No trip selected"}</span>
        </div>
        {selectedTrip && selectedEvent ? (
          <div className="buyer-detail-grid">
            <div>
              <div className="buyer-trip-heading">
                <span className="buyer-driver-avatar">{selectedTrip.driverId}</span>
                <div>
                  <h3>
                    {date.format(new Date(selectedTrip.startedAt))} ·{" "}
                    {time.format(new Date(selectedTrip.startedAt))}
                  </h3>
                  <p>
                    {number.format(selectedTrip.miles)} miles <span>·</span>{" "}
                    {selectedTrip.durationMinutes} min <span>·</span> {selectedTrip.events.length}{" "}
                    flagged {selectedTrip.events.length === 1 ? "event" : "events"}
                  </p>
                </div>
              </div>
              <div className="buyer-trip-timeline" aria-label="Events along the selected trip">
                <div className="buyer-timeline-track" />
                {selectedTrip.events.map((event) => (
                  <button
                    key={event.id}
                    className={`buyer-timeline-dot ${selectedEvent.id === event.id ? "is-selected" : ""}`}
                    aria-pressed={selectedEvent.id === event.id}
                    style={{
                      left: `${(event.offsetSeconds / (selectedTrip.durationMinutes * 60)) * 100}%`,
                    }}
                    aria-label={`${eventLabels[event.type]} at ${Math.floor(event.offsetSeconds / 60)} minutes`}
                    title={`${eventLabels[event.type]} · ${Math.floor(event.offsetSeconds / 60)} min`}
                    onClick={() => {
                      setEventType("all");
                      setSelectedEventId(event.id);
                    }}
                  />
                ))}
              </div>
              <div className="buyer-timeline-labels">
                <span>Trip starts</span>
                <span>{selectedTrip.durationMinutes} min · Trip ends</span>
              </div>
            </div>
            <div className="buyer-reason" aria-live="polite">
              <div className="buyer-reason-heading">
                <span>Why it was flagged</span>
              </div>
              <h3>{eventLabels[selectedEvent.type]}</h3>
              <p>{selectedEvent.detail}</p>
              <div className="buyer-rule">
                <span>
                  <strong>
                    {selectedEvent.value.toFixed(2)} {selectedEvent.unit}
                  </strong>{" "}
                  simulated reading
                </span>
                <ArrowRight size={15} />
                <span>
                  <strong>
                    {selectedEvent.threshold.toFixed(2)} {selectedEvent.unit}
                  </strong>{" "}
                  demo threshold
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="buyer-empty">
            <p>No event matches these filters. Clear them to explore a trip.</p>
          </div>
        )}
      </section>
    </main>
  );
}
