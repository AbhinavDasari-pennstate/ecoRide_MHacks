import {
  useStore,
  MAIN_TRIP,
  nowTs,
  type Action,
  type Message,
  type Booking,
  type Activity,
} from "./store";
import { mapTrip, windowLabel, type Bootstrap, type Dashboard, type ApiVehicle } from "./backend";

const base = (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "/api";
let metadata: Bootstrap | null = null;
let initialization: Promise<void> | null = null;
let refreshing: Promise<void> | null = null;
let cursor = 0;
const get = useStore.getState;
const set = useStore.setState;

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(60000),
    });
  } catch {
    throw new Error("Cannot reach the backend. Check that the API is running, then retry.");
  }
  const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string" ? detail : `Request failed (${response.status}). Please retry.`,
    );
  }
  return payload as T;
}

export function initialize(): Promise<void> {
  if (initialization) return initialization;
  initialization = (async () => {
    metadata = await request<Bootstrap>("/demo/bootstrap", "POST");
    set({
      users: metadata.users.map((u, i) => ({
        id: u.alias,
        backendId: u.id,
        name: u.name,
        role: u.roles.includes("driver")
          ? "Driver"
          : u.roles.includes("owner")
            ? "Owner"
            : "Passenger",
        dorm: "Ann Arbor campus",
        initials: u.name.slice(0, 2).toUpperCase(),
        hue: i * 47,
        edu: "",
      })),
    });
    await refresh();
    set({ ready: true, error: null });
  })().catch((error: unknown) => {
    initialization = null;
    throw error;
  });
  return initialization;
}

export function refresh(): Promise<void> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    if (!metadata) return;
    const alex = metadata.users.find((u) => u.alias === "alex")!;
    const [dashboard, available, impact, feed] = await Promise.all([
      request<Dashboard>(`/users/${alex.id}/dashboard`),
      request<ApiVehicle[]>("/vehicles?limit=500"),
      request<{ kg_co2_avoided: number; miles_avoided: number; trips: number }>("/impact"),
      request<{ events: Activity[]; last_id: number }>(`/events?since=${cursor}&limit=1000`),
    ]);
    const aliases = new Map(metadata.users.map((u) => [u.id, u.alias]));
    const rows = dashboard.trips.filter((t) => t.status !== "cancelled");
    const live = dashboard.matches.filter((m) => m.status !== "cancelled");
    const trips = rows.map((row, i) =>
      mapTrip(
        row,
        live.find((m) => m.driver_trip_id === row.id),
        aliases,
        i === 0,
      ),
    );
    const vehiclesById = new Map(available.map((v) => [v.id, v]));
    for (const m of live) if (m.vehicle) vehiclesById.set(m.vehicle.id, m.vehicle);
    const vehicles = [...vehiclesById.values()].map((v) => {
      const m = live.find((m) => m.vehicle_id === v.id);
      const option = trips[0]?.options.find((o) => o.vehicle_id === v.id);
      return {
        id: String(v.id),
        name: v.make_model,
        type: v.fuel_type === "ev" ? ("EV" as const) : ("Gas" as const),
        ownerId: aliases.get(v.owner_id) ?? String(v.owner_id),
        distanceMi: option?.deadhead_mi ?? 0,
        rate: v.price_per_hour_cents / 100,
        kgPerMi: 0,
        status: !v.active
          ? ("CANCELLED" as const)
          : m?.booking?.status === "approved"
            ? ("RESERVED" as const)
            : m?.booking?.status === "requested"
              ? ("PENDING" as const)
              : ("AVAILABLE" as const),
        window: windowLabel(v.avail_start, v.avail_end),
        color: "",
      };
    });
    const bookings: Booking[] = live.flatMap((m) => {
      const b = m.booking;
      const t = trips.find((t) => t.matchId === m.id);
      if (!b || !t) return [];
      return [
        {
          id: String(b.id),
          vehicleId: String(b.vehicle_id),
          tripId: t.id,
          requesterId: t.driverId,
          window: windowLabel(b.start_ts, b.end_ts),
          amount: b.price_cents / 100,
          status:
            b.status === "approved"
              ? "APPROVED"
              : b.status === "requested"
                ? "PENDING"
                : b.status === "declined"
                  ? "DECLINED"
                  : "CANCELLED",
        },
      ];
    });
    cursor = feed.last_id;
    set((s) => ({
      trips,
      vehicles,
      bookings,
      matches: (trips[0]?.participants ?? [])
        .filter((p) => p.role === "Passenger")
        .map((p) => ({
          userId: p.userId,
          pct: p.matchPct ?? 0,
          reason: "Compatible destination and departure window",
        })),
      campus: { kg: impact.kg_co2_avoided, miles: impact.miles_avoided, trips: impact.trips },
      events: [...s.events, ...feed.events].slice(-30),
      ui: {
        ...s.ui,
        ...(trips[0] ? { voiceLine: 4 } : {}),
        ...(trips[0]?.changed ? { disruption: "done" as const } : {}),
      },
    }));
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

export async function perform<T>(operation: () => Promise<T>): Promise<T | undefined> {
  try {
    return await operation();
  } catch (error) {
    set({ error: error instanceof Error ? error.message : "Something went wrong. Please retry." });
    return undefined;
  }
}

async function mutate<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
  if (get().busy) throw new Error("Please wait for the current update to finish.");
  set({ busy: true, error: null });
  try {
    if (refreshing) await refreshing;
    const result = await request<T>(path, method, body);
    await refresh();
    return result;
  } finally {
    set({ busy: false });
  }
}
const current = () => {
  const t = get().trips.find((t) => t.id === MAIN_TRIP);
  if (!t) throw new Error("Create a trip first.");
  return t;
};
const match = () => {
  const t = current();
  if (!t.matchId) throw new Error("No match yet. Retry matching.");
  return t.matchId;
};

export async function create_trip(_input?: {
  destination: string;
  day: string;
  time: string;
  driverId: string;
}) {
  await initialize();
  await mutate("/demo/trips");
  return MAIN_TRIP;
}
export async function find_matches(_tripId: string) {
  const t = current();
  await mutate("/planner/run", t.matchId ? { match_id: t.matchId } : { trip_id: t.backendTripId });
  return get().matches;
}
export async function get_match_details(userId: string) {
  await refresh();
  return get().matches.find((m) => m.userId === userId);
}
export async function accept_match(_tripId: string, userId: string) {
  const u = get().users.find((u) => u.id === userId);
  if (!u) throw new Error("Unknown participant.");
  await mutate(`/matches/${match()}/accept`, { user_id: u.backendId });
}
export async function reserve_vehicle(_tripId: string, vehicleId: string) {
  if (current().vehicleId !== vehicleId)
    await mutate(`/matches/${match()}/vehicle`, { vehicle_id: Number(vehicleId) });
}
export async function respond_booking(bookingId: string, approve: boolean) {
  await mutate(`/bookings/${bookingId}/${approve ? "approve" : "decline"}`);
}
export async function cancel_trip(_tripId: string, userId?: string) {
  const t = current();
  const id = userId
    ? t.participants.find((p) => p.userId === userId)?.backendTripId
    : t.backendTripId;
  if (!id) throw new Error("Participant is not in this trip.");
  await mutate(`/trips/${id}/cancel`);
}
export async function cancel_vehicle() {
  const id = current().vehicleId;
  if (!id) throw new Error("No vehicle to cancel.");
  await mutate(`/vehicles/${id}/cancel`);
}
export async function restart() {
  await mutate("/demo/restart");
  set({ messages: {}, sent: {}, ui: { voiceLine: 0, voiceBusy: false, disruption: "idle" } });
}
export async function get_sustainability_impact() {
  await refresh();
  return current().impact;
}

// The phone is an interactive demo panel. Booking actions are persisted by the API;
// these local presentation bubbles do not claim to send a real iMessage.
export async function sendMessage(userId: string, text: string, actions?: Action[]) {
  const m: Message = { id: crypto.randomUUID(), from: "bot", text, actions, ts: nowTs() };
  set((s) => ({ messages: { ...s.messages, [userId]: [...(s.messages[userId] ?? []), m] } }));
}
export async function handleAction(userId: string, action: Action) {
  if (action === "YES" || action === "ACCEPT") await accept_match(MAIN_TRIP, userId);
  else if (action === "APPROVE" || action === "DECLINE") {
    const vehicle = get().vehicles.find((v) => v.id === current().vehicleId);
    if (vehicle?.ownerId !== userId)
      throw new Error("Only the current vehicle's owner can approve this request.");
    const b = get().bookings.find((b) => b.tripId === MAIN_TRIP && b.status === "PENDING");
    if (!b) throw new Error("No pending booking.");
    await respond_booking(b.id, action === "APPROVE");
  } else await cancel_trip(MAIN_TRIP, userId);
  set((s) => ({
    messages: {
      ...s.messages,
      [userId]: [
        ...(s.messages[userId] ?? []).map((m) => ({ ...m, actions: undefined })),
        { id: crypto.randomUUID(), from: "me", text: action, ts: nowTs() },
      ],
    },
  }));
  await sendMessage(
    userId,
    action === "CANCEL"
      ? "Your cancellation is saved."
      : "Your response is saved. The trip confirms when every traveler and the vehicle owner approve.",
  );
}
