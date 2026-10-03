// Mock API. Each function mutates the central store after fake latency.
// Swap these bodies for real network calls later.
import { useStore, MAIN_TRIP, nowTs, type Action, type Trip, type Message } from "./store";

const wait = (min = 300, max = 800) => new Promise((r) => setTimeout(r, min + Math.random() * (max - min)));
const set = useStore.setState;
const get = useStore.getState;
let mid = 0;

const patchTrip = (id: string, fn: (t: Trip) => Partial<Trip>) =>
  set((s) => ({ trips: s.trips.map((t) => (t.id === id ? { ...t, ...fn(t) } : t)) }));

export async function sendMessage(userId: string, text: string, actions?: Action[]) {
  set((s) => ({ typing: { ...s.typing, [userId]: true } }));
  await wait(700, 1000);
  const m: Message = { id: `m${++mid}`, from: "bot", text, actions, ts: nowTs() };
  set((s) => ({ typing: { ...s.typing, [userId]: false }, messages: { ...s.messages, [userId]: [...(s.messages[userId] ?? []), m] } }));
}
export function userReply(userId: string, text: string) {
  set((s) => ({
    messages: {
      ...s.messages,
      [userId]: [...(s.messages[userId] ?? []).map((m) => ({ ...m, actions: undefined })), { id: `m${++mid}`, from: "me", text, ts: nowTs(), read: true }],
    },
  }));
}

export async function create_trip(input: { destination: string; day: string; time: string; driverId: string }) {
  await wait();
  if (get().trips.some((t) => t.id === MAIN_TRIP)) return MAIN_TRIP;
  const trip: Trip = {
    id: MAIN_TRIP, title: "Grocery run", destination: input.destination, day: input.day, time: input.time, departure: "2:00 PM",
    roundTripMi: 14.1, window: "1:45 to 4:15 PM", hours: 2.5, driverId: input.driverId,
    participants: [{ userId: input.driverId, role: "Driver", status: "CONFIRMED", pickup: "1:45 PM" }],
    vehicleState: "NONE", status: "REQUESTED",
  };
  set((s) => ({ trips: [trip, ...s.trips] }));
  return trip.id;
}

export async function find_matches(tripId: string) {
  patchTrip(tripId, () => ({ status: "MATCHING" }));
  await wait(600, 900);
  const matches = [
    { userId: "maya", pct: 94, reason: "Same dorm, same store, flexible 1 to 4 PM" },
    { userId: "jordan", pct: 89, reason: "Weekly Meijer run, budget under $10" },
  ];
  set({ matches });
  patchTrip(tripId, (t) => ({
    status: "PENDING",
    participants: [
      ...t.participants.filter((p) => p.role === "Driver"),
      { userId: "maya", role: "Passenger", status: "PENDING", matchPct: 94, pickup: "1:52 PM" },
      { userId: "jordan", role: "Passenger", status: "PENDING", matchPct: 89, pickup: "1:58 PM" },
    ],
  }));
  return matches;
}

export async function get_match_details(userId: string) {
  await wait();
  return get().matches.find((m) => m.userId === userId);
}

const recompute = (tripId: string) =>
  patchTrip(tripId, (t) => ({
    status: t.participants.every((p) => p.status === "CONFIRMED") && t.vehicleState === "RESERVED" ? "CONFIRMED" : "PENDING",
  }));

export async function accept_match(tripId: string, userId: string) {
  await wait();
  patchTrip(tripId, (t) => ({ participants: t.participants.map((p) => (p.userId === userId ? { ...p, status: "CONFIRMED" } : p)) }));
  recompute(tripId);
}

export async function list_vehicle(input: { name: string; type: "EV" | "Gas" | "Hybrid"; rate: number; window: string }) {
  await wait();
  const id = `v${Date.now()}`;
  set((s) => ({
    vehicles: [...s.vehicles, { id, ...input, ownerId: s.currentUserId === "alex" ? "sam" : s.currentUserId, distanceMi: 0.3, kgPerMi: input.type === "EV" ? 0.12 : input.type === "Hybrid" ? 0.22 : 0.4, status: "AVAILABLE", color: "New listing" }],
  }));
  return id;
}

export async function reserve_vehicle(tripId: string, vehicleId: string) {
  await wait();
  const t = get().trips.find((x) => x.id === tripId)!;
  const v = get().vehicles.find((x) => x.id === vehicleId)!;
  set((s) => ({
    vehicles: s.vehicles.map((x) => (x.id === vehicleId ? { ...x, status: "PENDING" } : x)),
    bookings: [...s.bookings.filter((b) => b.tripId !== tripId), { id: `b${Date.now()}`, vehicleId, tripId, requesterId: t.driverId, window: t.window, amount: v.rate * t.hours, status: "PENDING" }],
  }));
  patchTrip(tripId, () => ({ vehicleId, vehicleState: "PENDING" }));
}

export async function respond_booking(bookingId: string, approve: boolean) {
  await wait();
  const b = get().bookings.find((x) => x.id === bookingId);
  if (!b) return;
  set((s) => ({
    bookings: s.bookings.map((x) => (x.id === bookingId ? { ...x, status: approve ? "APPROVED" : "DECLINED" } : x)),
    vehicles: s.vehicles.map((x) => (x.id === b.vehicleId ? { ...x, status: approve ? "RESERVED" : "AVAILABLE" } : x)),
  }));
  patchTrip(b.tripId, () => ({ vehicleState: approve ? "RESERVED" : "NONE" }));
  recompute(b.tripId);
}

export async function modify_trip(tripId: string, patch: Partial<Trip>) {
  await wait();
  patchTrip(tripId, () => patch);
}

export async function cancel_trip(tripId: string, userId?: string) {
  await wait();
  if (userId) patchTrip(tripId, (t) => ({ participants: t.participants.map((p) => (p.userId === userId ? { ...p, status: "DECLINED" } : p)) }));
  else set((s) => ({ trips: s.trips.filter((t) => t.id !== tripId) }));
}

export async function get_sustainability_impact() {
  await wait();
  return { milesAvoided: 28.2, separate: 16.9, shared: 1.7, avoided: 15.2, pct: 90 };
}

// Route quick-reply chips to the right API call.
export async function handleAction(userId: string, action: Action) {
  userReply(userId, action);
  const t = get().trips.find((x) => x.id === MAIN_TRIP);
  if (!t) return;
  if (action === "YES") {
    await accept_match(MAIN_TRIP, userId);
    await sendMessage(userId, "You're confirmed. I'll remind you before pickup.");
  } else if (action === "ACCEPT") {
    await wait();
    // Accepting the new plan confirms every rider and the trip itself.
    set((s) => ({ messages: Object.fromEntries(Object.entries(s.messages).map(([k, v]) => [k, v.map((m) => ({ ...m, actions: undefined }))])) }));
    patchTrip(MAIN_TRIP, (t) => ({ participants: t.participants.map((p) => ({ ...p, status: "CONFIRMED" })), vehicleState: "RESERVED", status: "CONFIRMED" }));
    await sendMessage(userId, "Great, everyone is confirmed. See you at 2:04 PM.");
  } else if (action === "APPROVE" || action === "DECLINE") {
    const b = get().bookings.find((x) => x.tripId === MAIN_TRIP && x.status === "PENDING");
    if (b) await respond_booking(b.id, action === "APPROVE");
    await sendMessage(userId, action === "APPROVE" ? "Approved. Your Tesla is reserved 1:45 to 4:15 PM. $20 lands in your account after the trip." : "Declined. We'll find another car.");
  } else if (action === "CANCEL") {
    await cancel_trip(MAIN_TRIP, userId);
    await sendMessage(userId, "You've left the trip. No charge.");
  }
}
