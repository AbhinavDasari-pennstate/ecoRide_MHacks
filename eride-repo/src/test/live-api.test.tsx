import { describe, expect, it, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import * as api from "@/lib/api";
import { MAIN_TRIP, useStore } from "@/lib/store";
import { TripCard } from "@/components/TripCard";
import { ImpactSummary } from "@/components/Impact";

// Opt in against running dev servers: LIVE_API_URL=http://localhost:5173 npm test.
// Uses real HTTP, planning and PostgreSQL writes for the explicitly named demo
// accounts. Restart retains history and never truncates the database.
describe.skipIf(!process.env["LIVE_API_URL"])("frontend client → proxy → API → database", () => {
  it("persists a full trip, approvals, reload and replacement with authoritative numbers", async () => {
    const fetchNetwork = globalThis.fetch;
    vi.stubGlobal("fetch", (input: string | URL | Request, init?: RequestInit) =>
      fetchNetwork(new URL(String(input), process.env["LIVE_API_URL"]), init),
    );
    try {
      await api.initialize();
      expect(useStore.getState().ready).toBe(true);
      await api.restart();
      await api.create_trip();
      const current = () => useStore.getState().trips.find((t) => t.id === MAIN_TRIP)!;
      const first = current();
      expect(first.matchId).toBeGreaterThan(0);
      expect(first.participants).toHaveLength(3);
      expect(first.costs.perPerson).toBeGreaterThan(0);
      expect(first.impact.avoided).toBeGreaterThan(0);

      // A second create request is a retry, not a duplicate booking.
      await api.create_trip();
      expect(current().backendTripId).toBe(first.backendTripId);
      for (const p of first.participants) await api.accept_match(MAIN_TRIP, p.userId);
      expect(current().status).toBe("PENDING");
      const reservation = useStore.getState().bookings.find((b) => b.tripId === MAIN_TRIP)!;
      await api.respond_booking(reservation.id, true);
      expect(current().status).toBe("CONFIRMED");

      // Clear browser view data: the dashboard reconstructs the confirmed trip.
      useStore.setState({ trips: [], vehicles: [], bookings: [] });
      await api.refresh();
      expect(current().backendTripId).toBe(first.backendTripId);
      expect(current().status).toBe("CONFIRMED");
      expect(current().costs).toEqual(first.costs);
      render(
        <>
          <TripCard t={current()} />
          <ImpactSummary />
        </>,
      );
      expect(screen.getByText("Trip participants")).toBeInTheDocument();
      expect(screen.getByText("See assumptions")).toBeInTheDocument();
      cleanup();

      await api.cancel_vehicle();
      expect(current().vehicleId).not.toBe(first.vehicleId);
      expect(current().status).toBe("PENDING");
      expect(current().participants.every((p) => p.status === "PENDING")).toBe(true);
      const replacement = useStore.getState().bookings.find((b) => b.tripId === MAIN_TRIP)!;
      expect(replacement.status).toBe("PENDING");
      for (const p of current().participants) await api.accept_match(MAIN_TRIP, p.userId);
      await api.respond_booking(replacement.id, true);
      expect(current().status).toBe("CONFIRMED");
      const changedCost = current().costs;
      await api.refresh();
      expect(current().costs).toEqual(changedCost);
      expect(useStore.getState().events.some((e) => e.kind === "vehicle_cancelled")).toBe(true);
    } finally {
      cleanup();
      vi.unstubAllGlobals();
    }
  }, 180000);
});
