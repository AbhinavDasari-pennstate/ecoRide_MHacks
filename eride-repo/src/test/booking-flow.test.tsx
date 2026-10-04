import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { AccountTrip, AccountVehicle, SessionUser } from "@/lib/account-api";
import type { ApiMatch } from "@/lib/backend";
import { BookingFlow } from "@/routes/trip.$step";
import { OwnerPage } from "@/routes/owner";
import { Home } from "@/routes/index";
import { Profile } from "@/routes/profile";

const mocks = vi.hoisted(() => ({
  step: "1",
  trip: undefined as number | undefined,
  user: { id: 42, name: "Taylor", email: "taylor@example.com", role: "rider" } as SessionUser,
  dashboard: {
    trips: [] as AccountTrip[],
    matches: [] as ApiMatch[],
    vehicles: [] as AccountVehicle[],
  },
  request: vi.fn(),
  navigate: vi.fn(),
  refetch: vi.fn(),
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => () => ({
    useParams: () => ({ step: mocks.step }),
    useSearch: () => ({ trip: mocks.trip }),
  }),
  useNavigate: () => mocks.navigate,
  Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>,
}));
vi.mock("@/lib/account-api", () => ({
  accountRequest: (...args: unknown[]) => mocks.request(...args),
  useSession: () => ({ data: { user: mocks.user } }),
  useAccountDashboard: () => ({
    data: mocks.dashboard,
    isPending: false,
    refetch: mocks.refetch,
    error: null,
  }),
}));

function renderPage(children: ReactNode) {
  return render(children);
}

beforeEach(() => {
  mocks.step = "1";
  mocks.trip = undefined;
  mocks.user = { id: 42, name: "Taylor", email: "taylor@example.com", role: "rider" };
  mocks.dashboard = { trips: [], matches: [], vehicles: [] };
  mocks.request.mockReset();
  mocks.navigate.mockReset();
  mocks.refetch.mockReset();
  mocks.request.mockResolvedValue({ trip: { id: 91 } });
});
afterEach(cleanup);

describe("account booking", () => {
  it("creates the entered trip for the current account without using demo routes", async () => {
    renderPage(<BookingFlow />);
    fireEvent.change(screen.getByLabelText("Departure date"), { target: { value: "2099-10-10" } });
    fireEvent.change(screen.getByLabelText("Departure time"), { target: { value: "14:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Find my ride" }));
    await waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith(
        "/trips",
        expect.objectContaining({
          method: "POST",
          body: expect.objectContaining({
            user_id: 42,
            role: "passenger",
            dest_name: "Meijer (Ann Arbor-Saline Rd)",
            party_size: 1,
          }),
        }),
      ),
    );
    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith(
        expect.objectContaining({ params: { step: "2" }, search: { trip: 91 } }),
      ),
    );
    expect(mocks.request.mock.calls.some(([path]) => String(path).includes("demo"))).toBe(false);
  });

  it("finds a passenger's match and only lets the signed-in member accept", async () => {
    mocks.step = "3";
    mocks.trip = 91;
    mocks.dashboard.trips = [
      {
        id: 91,
        user_id: 42,
        role: "passenger",
        dest_name: "Meijer",
        window_start: "2099-10-10T18:00:00Z",
        window_end: "2099-10-10T18:45:00Z",
        status: "matched",
        party_size: 1,
      },
    ];
    mocks.dashboard.matches = [
      {
        id: 7,
        driver_trip_id: 90,
        depart_time: "2099-10-10T18:00:00Z",
        vehicle_id: 2,
        status: "proposed",
        members: [
          {
            trip_id: 90,
            user_id: 8,
            name: "Driver",
            role: "driver",
            status: "pending",
            match_score: null,
          },
          {
            trip_id: 91,
            user_id: 42,
            name: "Taylor",
            role: "passenger",
            status: "pending",
            match_score: 90,
          },
        ],
        vehicle: {
          id: 2,
          owner_id: 17,
          make_model: "Leaf",
          fuel_type: "ev",
          active: true,
          price_per_hour_cents: 800,
          efficiency: 0.27,
          avail_start: "2099-10-10T12:00:00Z",
          avail_end: "2099-10-10T23:00:00Z",
        },
        booking: {
          id: 4,
          vehicle_id: 2,
          status: "requested",
          start_ts: "2099-10-10T18:00:00Z",
          end_ts: "2099-10-10T20:00:00Z",
          price_cents: 1600,
        },
        total_cost_cents: 1200,
        cost_per_person_cents: 600,
        pricing: { group_size: 2, rental_hours: 2 },
        impact: null,
        route: null,
        assumptions: null,
        reasons: null,
        explanation: null,
        last_change: null,
      },
    ];
    renderPage(<BookingFlow />);
    expect(screen.getByText("Your group")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /accept for|approve as/i }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm my place" }));
    await waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("/matches/7/accept", {
        method: "POST",
        body: { user_id: 42 },
      }),
    );
  });

  it("shows an owner booking even when the owner has no trip", async () => {
    mocks.user.role = "owner";
    mocks.dashboard.matches = [
      {
        id: 7,
        driver_trip_id: 90,
        vehicle_id: 2,
        depart_time: "2099-10-10T18:00:00Z",
        vehicle: {
          id: 2,
          owner_id: 42,
          make_model: "Leaf",
          fuel_type: "ev",
          active: true,
          price_per_hour_cents: 800,
          efficiency: 0.27,
          avail_start: "2099-10-10T12:00:00Z",
          avail_end: "2099-10-10T23:00:00Z",
        },
        booking: {
          id: 4,
          vehicle_id: 2,
          status: "requested",
          start_ts: "2099-10-10T18:00:00Z",
          end_ts: "2099-10-10T20:00:00Z",
          price_cents: 1600,
        },
        members: [
          {
            trip_id: 90,
            user_id: 8,
            role: "driver",
            name: "Rider",
            status: "pending",
            match_score: null,
          },
        ],
        route: null,
        status: "proposed",
        cost_per_person_cents: 600,
        total_cost_cents: 1200,
        pricing: { group_size: 2, rental_hours: 2 },
        impact: null,
        assumptions: null,
        reasons: null,
        explanation: null,
        last_change: null,
      },
    ];
    renderPage(<OwnerPage />);
    fireEvent.click(screen.getByRole("button", { name: "Approve request" }));
    await waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("/bookings/4/approve", { method: "POST" }),
    );
  });

  it("keeps unmatched requests pending without showing a free or confirmed trip", () => {
    mocks.step = "2";
    mocks.trip = 91;
    mocks.dashboard.trips = [
      {
        id: 91,
        user_id: 42,
        role: "passenger",
        dest_name: "Meijer",
        window_start: "2099-10-10T18:00:00Z",
        window_end: "2099-10-10T18:45:00Z",
        status: "open",
        party_size: 1,
      },
    ];
    renderPage(<BookingFlow />);
    expect(screen.getByText("Your request is saved.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm my place" })).not.toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });

  it("rejects past departures without creating a trip", async () => {
    renderPage(<BookingFlow />);
    fireEvent.change(screen.getByLabelText("Departure date"), { target: { value: "2000-10-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Find my ride" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose a departure time in the future.",
    );
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("creates an owner listing for the signed-in owner", async () => {
    mocks.user.role = "owner";
    renderPage(<OwnerPage />);
    fireEvent.click(screen.getByRole("button", { name: "List a vehicle" }));
    fireEvent.change(screen.getByLabelText("Make and model"), { target: { value: "Nissan Leaf" } });
    fireEvent.change(screen.getByLabelText("Available from"), {
      target: { value: "2099-10-10T08:00" },
    });
    fireEvent.change(screen.getByLabelText("Available until"), {
      target: { value: "2099-10-10T22:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Publish listing" }));
    await waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith(
        "/vehicles",
        expect.objectContaining({
          method: "POST",
          body: expect.objectContaining({
            owner_id: 42,
            make_model: "Nissan Leaf",
            fuel_type: "ev",
            price_per_hour_cents: 800,
          }),
        }),
      ),
    );
  });

  it("offers landing-page actions that fit the signed-in role", () => {
    renderPage(<Home />);
    expect(screen.getByRole("link", { name: "Book a trip" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Share your car" })).not.toBeInTheDocument();
    expect(
      screen.getByText("Vehicle listings are available to owner accounts."),
    ).toBeInTheDocument();
    cleanup();
    mocks.user.role = "owner";
    renderPage(<Home />);
    expect(screen.getByRole("link", { name: "Share your car" })).toHaveAttribute("href", "/owner");
    cleanup();
    mocks.user.role = "buyer";
    renderPage(<Home />);
    expect(screen.getByRole("link", { name: "Open Data Portal" })).toHaveAttribute(
      "href",
      "/buyer",
    );
    expect(screen.queryByRole("link", { name: "Book a trip" })).not.toBeInTheDocument();
  });

  it("does not attach a continuing group to a cancelled trip in the profile", () => {
    mocks.dashboard.trips = [
      {
        id: 91,
        user_id: 42,
        role: "passenger",
        dest_name: "Meijer",
        window_start: "2099-10-10T18:00:00Z",
        window_end: "2099-10-10T18:45:00Z",
        status: "cancelled",
        party_size: 1,
      },
    ];
    mocks.dashboard.matches = [
      {
        id: 7,
        driver_trip_id: 90,
        vehicle_id: null,
        depart_time: "2099-10-10T18:00:00Z",
        status: "proposed",
        members: [
          {
            trip_id: 91,
            user_id: 42,
            name: "Taylor",
            role: "passenger",
            status: "cancelled",
            match_score: null,
          },
        ],
        vehicle: null,
        booking: null,
        cost_per_person_cents: 600,
        total_cost_cents: 1200,
        pricing: { group_size: 2, rental_hours: 2 },
        impact: null,
        assumptions: null,
        reasons: null,
        explanation: null,
        last_change: null,
        route: null,
      },
    ];
    renderPage(<Profile />);
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByText("$6.00")).not.toBeInTheDocument();
  });
});
