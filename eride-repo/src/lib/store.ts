import { create } from "zustand";

export const APP_NAME = "ERIDE";

export type Role = "Driver" | "Passenger" | "Owner";
export type User = { id: string; name: string; role: Role; dorm: string; initials: string; hue: number; edu: string };
export type VehicleStatus = "AVAILABLE" | "PENDING" | "RESERVED";
export type Vehicle = {
  id: string; name: string; type: "EV" | "Gas" | "Hybrid"; ownerId: string;
  distanceMi: number; rate: number; kgPerMi: number; status: VehicleStatus; window: string; color: string;
};
export type ParticipantStatus = "PENDING" | "CONFIRMED" | "DECLINED";
export type Participant = { userId: string; role: Role; status: ParticipantStatus; matchPct?: number; pickup: string };
export type TripVehicleState = "NONE" | "PENDING" | "RESERVED" | "LOST" | "REOPTIMIZING";
export type Trip = {
  id: string; title: string; destination: string; day: string; time: string; departure: string;
  roundTripMi: number; window: string; hours: number; driverId: string;
  participants: Participant[]; vehicleId?: string; vehicleState: TripVehicleState;
  status: "REQUESTED" | "MATCHING" | "PENDING" | "CONFIRMED"; changed?: boolean;
};
export type Booking = { id: string; vehicleId: string; tripId: string; requesterId: string; window: string; amount: number; status: "PENDING" | "APPROVED" | "DECLINED" };
export type Action = "YES" | "APPROVE" | "ACCEPT" | "CANCEL" | "DECLINE";
export type Message = { id: string; from: "bot" | "me"; text: string; actions?: Action[] | undefined; ts: string; read?: boolean };
export type Match = { userId: string; pct: number; reason: string };

export const USERS: User[] = [
  { id: "alex", name: "Alex Rivera", role: "Driver", dorm: "East Quad", initials: "AR", hue: 155, edu: "alex@umich.edu" },
  { id: "maya", name: "Maya Chen", role: "Passenger", dorm: "East Quad", initials: "MC", hue: 20, edu: "maya@umich.edu" },
  { id: "jordan", name: "Jordan Lee", role: "Passenger", dorm: "South Quad", initials: "JL", hue: 250, edu: "jordan@umich.edu" },
  { id: "sam", name: "Sam Patel", role: "Owner", dorm: "Baits II", initials: "SP", hue: 60, edu: "sam@umich.edu" },
  ...["Priya Nair", "Ethan Brooks", "Lena Fischer", "Omar Haddad", "Grace Kim", "Diego Santos", "Nora Walsh", "Kai Tanaka", "Zoe Martin", "Ravi Shah", "Ella Moore", "Ben Carter", "Ivy Zhang", "Luca Rossi", "Ama Owusu"].map(
    (n, i) => ({
      id: `u${i}`, name: n, role: (["Driver", "Passenger", "Owner"] as Role[])[i % 3]!,
      dorm: ["East Quad", "South Quad", "Baits II", "Mosher-Jordan", "North Quad"][i % 5]!,
      initials: n.split(" ").map((p) => p[0]).join(""), hue: (i * 47) % 360, edu: `${n.split(" ")[0]!.toLowerCase()}@umich.edu`,
    }),
  ),
];
export const userById = (id: string) => USERS.find((u) => u.id === id)!;

const seedVehicles = (): Vehicle[] => [
  { id: "tesla", name: "Tesla Model 3", type: "EV", ownerId: "sam", distanceMi: 0.8, rate: 8, kgPerMi: 0.12, status: "AVAILABLE", window: "Sat 12:00 to 6:00 PM", color: "Pearl white" },
  { id: "civic", name: "Honda Civic", type: "Gas", ownerId: "u2", distanceMi: 0.5, rate: 7, kgPerMi: 0.4, status: "AVAILABLE", window: "Sat 10:00 AM to 5:00 PM", color: "Graphite" },
  { id: "leaf", name: "Nissan Leaf", type: "EV", ownerId: "u5", distanceMi: 1.1, rate: 9, kgPerMi: 0.12, status: "AVAILABLE", window: "Sat 1:00 to 8:00 PM", color: "Deep blue" },
  { id: "prius", name: "Toyota Prius", type: "Hybrid", ownerId: "u8", distanceMi: 1.6, rate: 7.5, kgPerMi: 0.22, status: "RESERVED", window: "Sun all day", color: "Silver" },
  { id: "bolt", name: "Chevy Bolt", type: "EV", ownerId: "u11", distanceMi: 2.0, rate: 8.5, kgPerMi: 0.12, status: "AVAILABLE", window: "Weekdays after 5 PM", color: "Red" },
  { id: "corolla", name: "Toyota Corolla", type: "Gas", ownerId: "u14", distanceMi: 1.3, rate: 6.5, kgPerMi: 0.38, status: "AVAILABLE", window: "Fri evenings", color: "White" },
];

type State = {
  currentUserId: string;
  onboarded: boolean;
  vehicles: Vehicle[];
  trips: Trip[];
  matches: Match[];
  bookings: Booking[];
  messages: Record<string, Message[]>;
  typing: Record<string, boolean>;
  sent: Record<string, true>;
  campus: { kg: number; miles: number; trips: number };
  ui: { voiceLine: number; voiceBusy: boolean; disruption: "idle" | "running" | "done"; banner?: string | undefined };
};

const seed = (): State => ({
  currentUserId: "alex",
  onboarded: true,
  vehicles: seedVehicles(),
  trips: [
    {
      id: "t-lib", title: "Library late run", destination: "Hatcher Library", day: "Thu", time: "9:30 PM", departure: "9:30 PM",
      roundTripMi: 3.2, window: "9:15 to 10:30 PM", hours: 1.25, driverId: "u0",
      participants: [
        { userId: "u0", role: "Driver", status: "CONFIRMED", pickup: "9:15 PM" },
        { userId: "u3", role: "Passenger", status: "CONFIRMED", pickup: "9:20 PM" },
      ],
      vehicleId: "bolt", vehicleState: "RESERVED", status: "CONFIRMED",
    },
  ],
  matches: [],
  bookings: [],
  messages: { alex: [], maya: [], jordan: [], sam: [] },
  typing: {},
  sent: {},
  campus: { kg: 2710, miles: 7842, trips: 603 },
  ui: { voiceLine: 0, voiceBusy: false, disruption: "idle" },
});

export const useStore = create<State>(() => seed());
export const resetStore = () => useStore.setState(seed(), true);
export const setUi = (p: Partial<State["ui"]>) => useStore.setState((s) => ({ ui: { ...s.ui, ...p } }));

export const MAIN_TRIP = "t-meijer";
export const useMainTrip = () => useStore((s) => s.trips.find((t) => t.id === MAIN_TRIP));

export const tripCost = (t: Trip, vehicles: Vehicle[]) => {
  const v = vehicles.find((x) => x.id === t.vehicleId);
  const total = v ? v.rate * t.hours : 0;
  const people = Math.max(1, t.participants.length);
  return { total, perPerson: total / people, people };
};

export const impactFor = (t: Trip, vehicles: Vehicle[]) => {
  const v = vehicles.find((x) => x.id === t.vehicleId);
  const n = t.participants.length;
  const separate = +(n * t.roundTripMi * 0.4).toFixed(1);
  const shared = +(t.roundTripMi * (v?.kgPerMi ?? 0.4)).toFixed(1);
  return {
    milesAvoided: +((n - 1) * t.roundTripMi).toFixed(1),
    separate, shared, avoided: +(separate - shared).toFixed(1),
    pct: separate ? Math.round(((separate - shared) / separate) * 100) : 0,
  };
};

export const nowTs = () => new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
