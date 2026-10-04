import { useStore, setUi, MAIN_TRIP, type Action } from "./store";
import * as api from "./api";
const get = useStore.getState;
const trip = () => get().trips.find((t) => t.id === MAIN_TRIP);
export const SCRIPT: { who: "user" | "agent"; text: string; act?: boolean }[] = [
  {
    who: "user",
    text: "I need groceries at Meijer next Saturday. I can drive, but I don't have a car.",
  },
  { who: "agent", text: "We'll look for a shared afternoon trip." },
  { who: "user", text: "Around two works for me." },
  { who: "agent", text: "Creating your trip and finding compatible travelers.", act: true },
];
export async function advanceVoice() {
  const { voiceLine, voiceBusy } = get().ui;
  if (voiceBusy || get().busy || voiceLine >= SCRIPT.length) return;
  if (!SCRIPT[voiceLine]?.act) {
    setUi({ voiceLine: voiceLine + 1 });
    return;
  }
  setUi({ voiceBusy: true });
  try {
    await api.create_trip();
    setUi({ voiceLine: SCRIPT.length });
  } finally {
    setUi({ voiceBusy: false });
  }
}
export async function ensureTrip() {
  await api.initialize();
  if (!trip()) await api.create_trip();
}
export async function ensureMatches() {
  await ensureTrip();
  if (!trip()?.matchId) await api.find_matches(MAIN_TRIP);
}
export async function ensureVehicle() {
  await ensureMatches();
}
async function sendOnce(key: string, userId: string, text: string, actions?: Action[]) {
  if (get().sent[key]) return;
  await api.sendMessage(userId, text, actions);
  useStore.setState((s) => ({ sent: { ...s.sent, [key]: true } }));
}
export async function step4() {
  await ensureVehicle();
  const t = trip()!;
  for (const p of t.participants) {
    if (p.status !== "PENDING") continue;
    await sendOnce(
      `invite-${t.matchId}-${t.vehicleId}-${p.userId}-${t.costs.perPerson}`,
      p.userId,
      `${t.destination}, ${t.day} ${t.departure}. Estimated share $${t.costs.perPerson.toFixed(2)}. Group CO2 reduction ${t.impact.avoided.toFixed(2)} kg. Accept your place?`,
      ["YES", "CANCEL"],
    );
  }
}
export async function step5() {
  await ensureVehicle();
  const t = trip()!;
  const v = get().vehicles.find((v) => v.id === t.vehicleId);
  const b = get().bookings.find((b) => b.tripId === MAIN_TRIP && b.status === "PENDING");
  if (v && b)
    await sendOnce(
      `owner-${b.id}`,
      v.ownerId,
      `${v.name} requested ${t.day}, ${b.window}. Estimated rental $${b.amount.toFixed(2)}. Approve this booking?`,
      ["APPROVE", "DECLINE"],
    );
}
export async function simulateCancellation() {
  if (get().busy) return;
  setUi({ disruption: "running" });
  try {
    await api.cancel_vehicle();
    setUi({ disruption: "done" });
    await step4();
    await step5();
  } catch (error) {
    setUi({ disruption: "idle" });
    throw error;
  }
}
export const reset = () => api.restart();
