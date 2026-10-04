import { describe, expect, it } from "vitest";
import { datasetSummary, demoTrips, driverSummaries, drivingEvents } from "@/lib/buyerData";

describe("simulated buyer dataset", () => {
  it("keeps each event attached to a real trip, within its time window and above its demo threshold", () => {
    expect(demoTrips).toHaveLength(48);
    expect(new Set(demoTrips.map((trip) => trip.id)).size).toBe(48);
    expect(new Set(demoTrips.map((trip) => trip.driverId))).toEqual(
      new Set(["D1", "D2", "D3", "D4", "D5", "D6"]),
    );
    expect(new Set(demoTrips.map((trip) => trip.startedAt.slice(0, 10))).size).toBe(9);
    expect(drivingEvents.length).toBeGreaterThan(0);
    expect(new Set(drivingEvents.map((event) => event.id)).size).toBe(drivingEvents.length);
    for (const trip of demoTrips) {
      const start = Date.parse(trip.startedAt);
      expect(start).toBeGreaterThanOrEqual(Date.parse("2026-09-21T00:00:00Z"));
      expect(start + trip.durationMinutes * 60_000).toBeLessThan(
        Date.parse("2026-09-30T00:00:00Z"),
      );
      expect(trip.miles).toBeGreaterThan(0);
      expect(trip.durationMinutes).toBeGreaterThan(0);
      expect(trip.estimatedEnergyKwh).toBeGreaterThan(0);
      for (const event of trip.events) {
        expect(event.tripId).toBe(trip.id);
        expect(event.driverId).toBe(trip.driverId);
        expect(event.offsetSeconds).toBeGreaterThan(0);
        expect(event.offsetSeconds).toBeLessThan(trip.durationMinutes * 60);
        expect(Date.parse(event.timestamp)).toBe(start + event.offsetSeconds * 1_000);
        expect(event.value).toBeGreaterThan(event.threshold);
        expect(event.unit).toBe("g");
        expect(event.detail).toContain("simulated");
        expect(event.detail).toContain(event.threshold.toFixed(2));
        expect(["Review", "Watch"]).toContain(event.severity);
      }
    }
    expect(drivingEvents).toEqual(
      demoTrips
        .flatMap((trip) => trip.events)
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    );
  });

  it("derives dashboard totals and rates from the same trips shown in drilldowns", () => {
    expect(datasetSummary).toMatchObject({
      vehicle: "Tesla Model 3",
      driverCount: 6,
      tripCount: 48,
      dayCount: 9,
      startDate: "2026-09-21",
      endDate: "2026-09-29",
    });
    expect(datasetSummary.miles).toBeCloseTo(
      demoTrips.reduce((sum, trip) => sum + trip.miles, 0),
      1,
    );
    expect(datasetSummary.estimatedEnergyKwh).toBeCloseTo(
      demoTrips.reduce((sum, trip) => sum + trip.estimatedEnergyKwh, 0),
      1,
    );
    expect(datasetSummary.eventCount).toBe(drivingEvents.length);
    expect(driverSummaries).toHaveLength(6);
    for (const driver of driverSummaries) {
      const trips = demoTrips.filter((trip) => trip.driverId === driver.id);
      const events = trips.flatMap((trip) => trip.events);
      const miles = trips.reduce((sum, trip) => sum + trip.miles, 0);
      const energy = trips.reduce((sum, trip) => sum + trip.estimatedEnergyKwh, 0);
      const hardBrakes = events.filter((event) => event.type === "hard_brake").length;
      expect(driver.trips).toBe(trips.length);
      expect(driver.miles).toBeCloseTo(miles, 1);
      expect(driver.events).toBe(events.length);
      expect(driver.hardBrakes).toBe(hardBrakes);
      expect(driver.rapidAccelerations).toBe(
        events.filter((event) => event.type === "rapid_acceleration").length,
      );
      expect(driver.hardBrakesPer100Miles).toBeCloseTo((hardBrakes / miles) * 100, 1);
      expect(driver.energyPer100Miles).toBeCloseTo((energy / miles) * 100, 1);
    }
  });

  it("includes the review boundary and keeps values below it on Watch", () => {
    expect(
      drivingEvents.find((event) => event.type === "rapid_acceleration" && event.value === 0.35),
    ).toMatchObject({ severity: "Review", threshold: 0.25 });
    expect(
      drivingEvents.find((event) => event.type === "rapid_acceleration" && event.value === 0.32),
    ).toMatchObject({ severity: "Watch", threshold: 0.25 });
    expect(
      drivingEvents.find((event) => event.type === "hard_brake" && event.value === 0.39),
    ).toMatchObject({ severity: "Watch", threshold: 0.3 });
    expect(
      drivingEvents.find((event) => event.type === "hard_brake" && event.value === 0.42),
    ).toMatchObject({ severity: "Review", threshold: 0.3 });
  });
  it("contains both calm driving and a visibly higher event rate for comparison", () => {
    const calm = driverSummaries.find((driver) => driver.id === "D1")!;
    const flagged = driverSummaries.find((driver) => driver.id === "D5")!;
    expect(calm.events).toBe(0);
    expect(flagged.events).toBeGreaterThan(10);
    expect(flagged.hardBrakesPer100Miles).toBeGreaterThan(calm.hardBrakesPer100Miles);
    expect(new Set(drivingEvents.map((event) => event.type))).toEqual(
      new Set(["hard_brake", "rapid_acceleration", "sharp_turn"]),
    );
  });
});
