import { useStore, setUi, MAIN_TRIP, resetStore, type Action } from "./store";
import * as api from "./api";

const get = useStore.getState;
const trip = () => get().trips.find((t) => t.id === MAIN_TRIP);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const SCRIPT: { who: "user" | "agent"; text: string; act?: boolean }[] = [
  { who: "user", text: "I need to get groceries at Meijer next Saturday afternoon. I can drive, but I don't have a car." },
  { who: "agent", text: "Got it. Around what time?" },
  { who: "user", text: "Around two." },
  { who: "agent", text: "I've created your trip request.", act: true },
];

export async function advanceVoice() {
  const { voiceLine, voiceBusy } = get().ui;
  if (voiceBusy || voiceLine >= SCRIPT.length) return;
  const line = SCRIPT[voiceLine]!;
  setUi({ voiceLine: voiceLine + 1 });
  if (line.act) {
    setUi({ voiceBusy: true });
    await api.create_trip({ destination: "Meijer", day: "Sat", time: "2:00 PM", driverId: "alex" });
    setUi({ voiceBusy: false });
  }
}
export const voiceDone = () => get().ui.voiceLine >= SCRIPT.length && !get().ui.voiceBusy && !!trip();

// Sends a scripted text only once per key, so re-mounting a step never duplicates bubbles.
function sendOnce(key: string, userId: string, text: string, actions?: Action[]) {
  if (get().sent[key]) return false;
  useStore.setState((s) => ({ sent: { ...s.sent, [key]: true } }));
  return api.sendMessage(userId, text, actions);
}

export async function ensureTrip() {
  if (!trip()) await api.create_trip({ destination: "Meijer", day: "Sat", time: "2:00 PM", driverId: "alex" });
}
export async function ensureMatches() {
  await ensureTrip();
  if (trip()!.participants.length < 3) await api.find_matches(MAIN_TRIP);
}
export async function ensureVehicle() {
  await ensureMatches();
  if (!trip()!.vehicleId) await api.reserve_vehicle(MAIN_TRIP, "tesla");
}

const INVITE = "Grocery trip found. Meijer, Saturday 2 PM. $6.67 estimated share. 15.2 kg CO2 avoided. Reply YES to join.";

export async function step4() {
  await ensureVehicle();
  if (get().sent["maya-invite"]) return;
  sendOnce("jordan-invite", "jordan", INVITE, ["YES"]);
  await sendOnce("maya-invite", "maya", INVITE, ["YES"]);
  // Jordan accepts on his own phone a moment later so the group fills out.
  setTimeout(() => {
    const j = trip()?.participants.find((p) => p.userId === "jordan");
    if (j?.status === "PENDING") api.handleAction("jordan", "YES");
  }, 4000);
}
export async function step5() {
  await ensureVehicle();
  await sendOnce("sam-request", "sam", "Your Tesla has been requested Saturday 1:45 to 4:15 PM. Estimated rental: $20. Reply APPROVE.", ["APPROVE", "DECLINE"]);
}

export async function simulateCancellation() {
  if (get().ui.disruption !== "idle") return;
  setUi({ disruption: "running" });
  await ensureVehicle();
  const s = useStore.setState;
  s((st) => ({ vehicles: st.vehicles.map((v) => (v.id === "tesla" ? { ...v, status: "AVAILABLE" } : v)) }));
  await api.modify_trip(MAIN_TRIP, { vehicleState: "LOST", status: "PENDING" });
  await sleep(1600);
  await api.modify_trip(MAIN_TRIP, { vehicleState: "REOPTIMIZING" });
  await sleep(2200);
  s((st) => ({ vehicles: st.vehicles.map((v) => (v.id === "leaf" ? { ...v, status: "RESERVED" } : v)) }));
  await api.modify_trip(MAIN_TRIP, {
    vehicleId: "leaf", vehicleState: "RESERVED", departure: "2:04 PM", changed: true,
    participants: trip()!.participants.map((p) => ({
      ...p, status: p.role === "Driver" ? "CONFIRMED" : "PENDING",
      pickup: p.userId === "alex" ? "1:49 PM" : p.userId === "maya" ? "1:56 PM" : "2:02 PM",
    })),
  });
  setUi({ disruption: "done" });
  const msg = "Your vehicle changed but your grocery trip is still on. New departure: 2:04 PM. New cost: $7.50 per person. Reply ACCEPT or CANCEL.";
  sendOnce("change-jordan", "jordan", msg, ["ACCEPT", "CANCEL"]);
  await sendOnce("change-maya", "maya", msg, ["ACCEPT", "CANCEL"]);
}

export const reset = () => resetStore();
