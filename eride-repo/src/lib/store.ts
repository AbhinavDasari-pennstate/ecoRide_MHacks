import { create } from "zustand";

export const APP_NAME = "ERIDE";
export const MAIN_TRIP = "current-trip";
export type Role = "Driver" | "Passenger" | "Owner";
export type User = {
  id: string;
  backendId: number;
  name: string;
  role: Role;
  dorm: string;
  initials: string;
  hue: number;
  edu: string;
};
export type VehicleStatus = "AVAILABLE" | "PENDING" | "RESERVED" | "CANCELLED";
export type Vehicle = {
  id: string;
  name: string;
  type: "EV" | "Gas";
  ownerId: string;
  distanceMi: number;
  rate: number;
  kgPerMi: number;
  status: VehicleStatus;
  window: string;
  color: string;
};
export type Participant = {
  userId: string;
  backendTripId: number;
  role: Role;
  status: "PENDING" | "CONFIRMED" | "DECLINED";
  matchPct?: number | undefined;
  pickup: string;
};
export type Impact = {
  milesAvoided: number;
  separate: number;
  shared: number;
  avoided: number;
  pct: number;
};
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
export type Trip = {
  id: string;
  backendTripId: number;
  matchId?: number | undefined;
  title: string;
  destination: string;
  day: string;
  time: string;
  departure: string;
  roundTripMi: number;
  window: string;
  hours: number;
  driverId: string;
  participants: Participant[];
  vehicleId?: string | undefined;
  vehicleState: "NONE" | "PENDING" | "RESERVED" | "LOST" | "REOPTIMIZING";
  status: "REQUESTED" | "MATCHING" | "PENDING" | "CONFIRMED";
  changed?: boolean | undefined;
  costs: { total: number; perPerson: number; people: number };
  impact: Impact;
  assumptions: Record<string, unknown>;
  options: VehicleOption[];
  explanation: string;
  stops: Stop[];
  distanceSource: string;
};
export type Booking = {
  id: string;
  vehicleId: string;
  tripId: string;
  requesterId: string;
  window: string;
  amount: number;
  status: "PENDING" | "APPROVED" | "DECLINED" | "CANCELLED";
};
export type Action = "YES" | "APPROVE" | "ACCEPT" | "CANCEL" | "DECLINE";
export type Message = {
  id: string;
  from: "bot" | "me";
  text: string;
  actions?: Action[] | undefined;
  ts: string;
  read?: boolean;
};
export type Match = { userId: string; pct: number; reason: string };
export type Activity = { id: number; ts: string; kind: string; payload: Record<string, unknown> };
type State = {
  currentUserId: string;
  users: User[];
  vehicles: Vehicle[];
  trips: Trip[];
  matches: Match[];
  bookings: Booking[];
  messages: Record<string, Message[]>;
  typing: Record<string, boolean>;
  sent: Record<string, true>;
  campus: { kg: number; miles: number; trips: number };
  events: Activity[];
  ready: boolean;
  busy: boolean;
  error: string | null;
  ui: {
    voiceLine: number;
    voiceBusy: boolean;
    disruption: "idle" | "running" | "done";
    banner?: string | undefined;
  };
};
const initial = (): State => ({
  currentUserId: "alex",
  users: [],
  vehicles: [],
  trips: [],
  matches: [],
  bookings: [],
  messages: {},
  typing: {},
  sent: {},
  campus: { kg: 0, miles: 0, trips: 0 },
  events: [],
  ready: false,
  busy: false,
  error: null,
  ui: { voiceLine: 0, voiceBusy: false, disruption: "idle" },
});
export const useStore = create<State>(() => initial());
export const resetStore = () => useStore.setState(initial(), true);
export const setUi = (p: Partial<State["ui"]>) =>
  useStore.setState((s) => ({ ui: { ...s.ui, ...p } }));
export const useMainTrip = () => useStore((s) => s.trips.find((t) => t.id === MAIN_TRIP));
export const userById = (id: string): User =>
  useStore.getState().users.find((u) => u.id === id) ?? {
    id,
    backendId: 0,
    name: "Participant",
    role: "Passenger",
    dorm: "Campus",
    initials: "P",
    hue: 155,
    edu: "",
  };
export const tripCost = (t: Trip, _vehicles: Vehicle[]) => t.costs;
export const impactFor = (t: Trip, _vehicles: Vehicle[]) => t.impact;
export const nowTs = () =>
  new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
