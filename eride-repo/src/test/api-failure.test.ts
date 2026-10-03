import { expect, it, vi } from "vitest";
import { accept_match, perform } from "@/lib/api";
import { mapTrip } from "@/lib/backend";
import { useStore, MAIN_TRIP } from "@/lib/store";

it("shows a network failure without locally inventing a confirmation", async () => {
  const t = mapTrip(
    {
      id: 10,
      user_id: 1,
      dest_name: "Meijer",
      window_start: "2026-10-10T17:45:00Z",
      window_end: "2026-10-10T18:30:00Z",
      status: "matched",
    },
    undefined,
    new Map([[1, "alex"]]),
    true,
  );
  t.matchId = 7;
  useStore.setState({
    trips: [t],
    users: [
      {
        id: "alex",
        backendId: 1,
        name: "Alex",
        role: "Driver",
        dorm: "Campus",
        initials: "A",
        hue: 100,
        edu: "",
      },
    ],
  });
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  try {
    await perform(() => accept_match(MAIN_TRIP, "alex"));
    expect(useStore.getState().error).toContain("Cannot reach the backend");
    expect(useStore.getState().busy).toBe(false);
    expect(useStore.getState().trips[0]?.participants[0]?.status).toBe("PENDING");
  } finally {
    vi.unstubAllGlobals();
  }
});
