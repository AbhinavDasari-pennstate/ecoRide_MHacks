export type DrivingEvent = {
  id: string;
  tripId: string;
  driverId: string;
  type: "hard_brake" | "rapid_acceleration" | "sharp_turn";
  timestamp: string;
  offsetSeconds: number;
  severity: "Review" | "Watch";
  detail: string;
  value: number;
  unit: string;
  threshold: number;
};

export type DemoTrip = {
  id: string;
  driverId: string;
  startedAt: string;
  miles: number;
  durationMinutes: number;
  estimatedEnergyKwh: number;
  events: DrivingEvent[];
};

export const eventLabels: Record<DrivingEvent["type"], string> = {
  hard_brake: "Hard braking",
  rapid_acceleration: "Rapid acceleration",
  sharp_turn: "Sharp turn",
};

const round = (value: number) => Math.round(value * 100) / 100;

// Illustrative thresholds for the demo only, not a validated safety or risk model.
const eventRules: { type: DrivingEvent["type"]; threshold: number; measure: string }[] = [
  { type: "hard_brake", threshold: 0.3, measure: "deceleration" },
  { type: "rapid_acceleration", threshold: 0.25, measure: "acceleration" },
  { type: "sharp_turn", threshold: 0.3, measure: "lateral acceleration" },
];
const drivers = [
  { id: "D1", peaks: [0.14, 0.1, 0.13] },
  { id: "D2", peaks: [0.26, 0.2, 0.22] },
  { id: "D3", peaks: [0.3, 0.27, 0.26] },
  { id: "D4", peaks: [0.24, 0.29, 0.27] },
  { id: "D5", peaks: [0.39, 0.24, 0.3] },
  { id: "D6", peaks: [0.22, 0.18, 0.18] },
];
const tripDistances = [6.8, 12.4, 17.3, 10.2, 24.6, 8.9, 15.7, 19.1];

// Fixed inputs keep the same simulated journeys visible in charts, details and exports.
export const demoTrips: DemoTrip[] = Array.from({ length: 48 }, (_, index) => {
  const driverIndex = index % drivers.length;
  const driver = drivers[driverIndex]!;
  const tripNumber = Math.floor(index / drivers.length);
  const id = `TR-${String(index + 1).padStart(3, "0")}`;
  const start = Date.UTC(2026, 8, 21 + Math.floor((index * 9) / 48), 12 + driverIndex * 2);
  const miles = round(tripDistances[tripNumber]! + driverIndex * 0.7);
  const durationMinutes = Math.round(miles * 2.2 + 5);
  const events = eventRules.flatMap((rule, eventIndex): DrivingEvent[] => {
    const value = round(
      driver.peaks[eventIndex]! + ((tripNumber + driverIndex + eventIndex) % 5) * 0.03,
    );
    if (value <= rule.threshold) return [];
    const offsetSeconds = Math.round((durationMinutes * 60 * (eventIndex + 1)) / 4);
    const reviewThreshold = round(rule.threshold + 0.1);
    const severity = value >= reviewThreshold ? "Review" : "Watch";
    return [
      {
        id: `${id}-E${eventIndex + 1}`,
        tripId: id,
        driverId: driver.id,
        type: rule.type,
        timestamp: new Date(start + offsetSeconds * 1_000).toISOString(),
        offsetSeconds,
        severity,
        detail: `Peak simulated ${rule.measure} reached ${value.toFixed(2)} g, above the ${rule.threshold.toFixed(2)} g demo threshold. Review starts at ${reviewThreshold.toFixed(2)} g; lower flagged values are Watch.`,
        value,
        unit: "g",
        threshold: rule.threshold,
      },
    ];
  });
  return {
    id,
    driverId: driver.id,
    startedAt: new Date(start).toISOString(),
    miles,
    durationMinutes,
    // Synthetic energy estimate; no measured consumption or prediction model is used.
    estimatedEnergyKwh: round(miles * (0.23 + driverIndex * 0.01 + (tripNumber % 3) * 0.005)),
    events,
  };
}).sort((a, b) => b.startedAt.localeCompare(a.startedAt));

export const drivingEvents: DrivingEvent[] = demoTrips
  .flatMap((trip) => trip.events)
  .sort((a, b) => b.timestamp.localeCompare(a.timestamp));

export const driverSummaries = drivers.map(({ id }) => {
  const trips = demoTrips.filter((trip) => trip.driverId === id);
  const miles = trips.reduce((sum, trip) => sum + trip.miles, 0);
  const events = trips.flatMap((trip) => trip.events);
  const hardBrakes = events.filter((event) => event.type === "hard_brake").length;
  const energy = trips.reduce((sum, trip) => sum + trip.estimatedEnergyKwh, 0);
  return {
    id,
    trips: trips.length,
    miles: round(miles),
    hardBrakes,
    rapidAccelerations: events.filter((event) => event.type === "rapid_acceleration").length,
    events: events.length,
    hardBrakesPer100Miles: round((hardBrakes / miles) * 100),
    energyPer100Miles: round((energy / miles) * 100),
  };
});

const dates = [...new Set(demoTrips.map((trip) => trip.startedAt.slice(0, 10)))].sort();
export const datasetSummary = {
  vehicle: "Tesla Model 3",
  driverCount: new Set(demoTrips.map((trip) => trip.driverId)).size,
  tripCount: demoTrips.length,
  dayCount: dates.length,
  miles: round(demoTrips.reduce((sum, trip) => sum + trip.miles, 0)),
  eventCount: drivingEvents.length,
  estimatedEnergyKwh: round(demoTrips.reduce((sum, trip) => sum + trip.estimatedEnergyKwh, 0)),
  startDate: dates[0]!,
  endDate: dates[dates.length - 1]!,
};
