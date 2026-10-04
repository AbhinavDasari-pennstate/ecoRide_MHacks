export type VehicleOption = {
  vehicle_id: number;
  make_model?: string;
  fuel_type?: string;
  feasible: boolean;
  kg_co2: number;
  deadhead_mi: number;
  total_cost_cents: number;
  why_not: string[];
};
export type Stop = { name: string; lat: number; lng: number; kind: string };

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
