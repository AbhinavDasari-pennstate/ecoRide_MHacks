import { MAIN_TRIP, type Trip, type VehicleOption, type Stop } from "./store";

export type ApiUser = { id: number; alias: string; name: string; roles: string[] };
export type ApiVehicle = {
  id: number;
  owner_id: number;
  make_model: string;
  fuel_type: "ev" | "gas";
  active: boolean;
  price_per_hour_cents: number;
  efficiency: number;
  avail_start: string;
  avail_end: string;
};
export type ApiTrip = {
  id: number;
  user_id: number;
  dest_name: string;
  window_start: string;
  window_end: string;
  status: string;
};
export type ApiBooking = {
  id: number;
  vehicle_id: number;
  status: string;
  start_ts: string;
  end_ts: string;
  price_cents: number;
};
export type ApiMatch = {
  id: number;
  driver_trip_id: number;
  vehicle_id: number | null;
  depart_time: string;
  status: string;
  members: {
    trip_id: number;
    user_id: number;
    name: string;
    role: string;
    status: string;
    match_score: number | null;
  }[];
  vehicle: ApiVehicle | null;
  booking: ApiBooking | null;
  total_cost_cents: number | null;
  cost_per_person_cents: number | null;
  pricing: { group_size: number; rental_hours: number } | null;
  impact: {
    shared_miles: number;
    miles_avoided: number;
    kg_co2_baseline: number;
    kg_co2_shared: number;
    kg_co2_avoided: number;
    percent_reduction: number;
  } | null;
  assumptions: Record<string, unknown> | null;
  reasons: { vehicle_options: VehicleOption[] } | null;
  route: { stops: Stop[]; source: string } | null;
  explanation: string | null;
  last_change: { cause: string } | null;
};
export type Bootstrap = {
  users: ApiUser[];
  vehicles: ApiVehicle[];
  window_start: string;
  window_end: string;
};
export type Dashboard = { trips: ApiTrip[]; matches: ApiMatch[] };
export const campusTime = (date: string) =>
  new Date(date).toLocaleTimeString("en-US", {
    timeZone: "America/Detroit",
    hour: "numeric",
    minute: "2-digit",
  });
export const campusDay = (date: string) =>
  new Date(date).toLocaleDateString("en-US", {
    timeZone: "America/Detroit",
    weekday: "short",
    month: "short",
    day: "numeric",
  });
export const windowLabel = (start: string, end: string) =>
  `${campusTime(start)} – ${campusTime(end)}`;

export function mapTrip(
  row: ApiTrip,
  m: ApiMatch | undefined,
  aliases: Map<number, string>,
  current: boolean,
): Trip {
  const imp = m?.impact;
  const depart = m?.depart_time ?? row.window_start;
  const people = m?.pricing?.group_size ?? 1;
  return {
    id: current ? MAIN_TRIP : `trip-${row.id}`,
    backendTripId: row.id,
    matchId: m?.id,
    title: "Shared grocery trip",
    destination: row.dest_name,
    day: campusDay(depart),
    time: campusTime(depart),
    departure: campusTime(depart),
    roundTripMi: imp?.shared_miles ?? 0,
    window: m?.booking
      ? windowLabel(m.booking.start_ts, m.booking.end_ts)
      : windowLabel(row.window_start, row.window_end),
    hours: m?.pricing?.rental_hours ?? 0,
    driverId: aliases.get(row.user_id) ?? String(row.user_id),
    participants: m
      ? m.members
          .filter((p) => p.status !== "cancelled")
          .map((p) => ({
            userId: aliases.get(p.user_id) ?? String(p.user_id),
            backendTripId: p.trip_id,
            role: p.role === "driver" ? "Driver" : "Passenger",
            status: p.status === "accepted" ? "CONFIRMED" : "PENDING",
            matchPct: p.match_score == null ? undefined : Math.round(p.match_score),
            pickup: "At departure",
          }))
      : [
          {
            userId: aliases.get(row.user_id) ?? String(row.user_id),
            backendTripId: row.id,
            role: "Driver",
            status: "PENDING",
            pickup: campusTime(depart),
          },
        ],
    vehicleId: m?.vehicle_id == null ? undefined : String(m.vehicle_id),
    vehicleState:
      m?.status === "at_risk"
        ? "LOST"
        : !m?.vehicle_id
          ? "NONE"
          : m.booking?.status === "approved"
            ? "RESERVED"
            : "PENDING",
    status: m?.status === "confirmed" ? "CONFIRMED" : m ? "PENDING" : "REQUESTED",
    changed: m?.last_change?.cause === "vehicle_cancelled",
    costs: {
      total: (m?.total_cost_cents ?? 0) / 100,
      perPerson: (m?.cost_per_person_cents ?? 0) / 100,
      people,
    },
    impact: {
      milesAvoided: imp?.miles_avoided ?? 0,
      separate: imp?.kg_co2_baseline ?? 0,
      shared: imp?.kg_co2_shared ?? 0,
      avoided: imp?.kg_co2_avoided ?? 0,
      pct: imp?.percent_reduction ?? 0,
    },
    assumptions: m?.assumptions ?? {},
    options: m?.reasons?.vehicle_options ?? [],
    explanation: m?.explanation ?? "Waiting for a compatible group.",
    stops: m?.route?.stops ?? [],
    distanceSource: m?.route?.source ?? "pending",
  };
}
