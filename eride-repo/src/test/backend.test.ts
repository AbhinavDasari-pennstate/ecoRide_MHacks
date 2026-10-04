import { describe, expect, it } from "vitest";
import { mapTrip, type ApiTrip, type ApiMatch } from "@/lib/backend";

const row: ApiTrip = {
  id: 42,
  user_id: 12,
  dest_name: "Meijer",
  window_start: "2026-10-10T17:45:00Z",
  window_end: "2026-10-10T18:30:00Z",
  status: "matched",
};
const aliases = new Map([
  [12, "alex"],
  [15, "maya"],
]);
const match: ApiMatch = {
  id: 7,
  driver_trip_id: 42,
  vehicle_id: 23,
  depart_time: row.window_start,
  status: "proposed",
  members: [
    {
      trip_id: 42,
      user_id: 12,
      name: "Alex",
      role: "driver",
      status: "accepted",
      match_score: null,
    },
    {
      trip_id: 43,
      user_id: 15,
      name: "Maya",
      role: "passenger",
      status: "pending",
      match_score: 93.4,
    },
  ],
  vehicle: null,
  booking: {
    id: 9,
    vehicle_id: 23,
    status: "requested",
    start_ts: row.window_start,
    end_ts: row.window_end,
    price_cents: 1200,
  },
  total_cost_cents: 1284,
  cost_per_person_cents: 642,
  pricing: { group_size: 2, rental_hours: 1.5 },
  impact: {
    shared_miles: 11.2,
    miles_avoided: 8.3,
    kg_co2_baseline: 7.8,
    kg_co2_shared: 1.25,
    kg_co2_avoided: 6.55,
    percent_reduction: 84,
  },
  assumptions: { distance_source: "estimate" },
  reasons: { vehicle_options: [] },
  route: { stops: [], source: "estimate" },
  explanation: "Shared trip",
  last_change: null,
};
describe("database view adapter", () => {
  it("keeps backend IDs, rounded cents and emissions instead of recomputing them", () => {
    const t = mapTrip(row, match, aliases, true);
    expect(t.backendTripId).toBe(42);
    expect(t.matchId).toBe(7);
    expect(t.vehicleId).toBe("23");
    expect(t.costs).toEqual({ total: 12.84, perPerson: 6.42, people: 2 });
    expect(t.impact.avoided).toBe(6.55);
    expect(t.participants[1]?.backendTripId).toBe(43);
    expect(t.participants[1]?.status).toBe("PENDING");
  });
  it("does not mark a replacement confirmed before everyone and the owner approve", () => {
    const t = mapTrip(
      row,
      { ...match, last_change: { cause: "vehicle_cancelled" } },
      aliases,
      true,
    );
    expect(t.status).toBe("PENDING");
    expect(t.vehicleState).toBe("PENDING");
    expect(t.changed).toBe(true);
  });
  it("handles unmatched trips and distinguishes persisted at-risk matches", () => {
    expect(mapTrip(row, undefined, aliases, true).vehicleState).toBe("NONE");
    expect(mapTrip(row, { ...match, status: "at_risk" }, aliases, true).vehicleState).toBe("LOST");
  });
});
