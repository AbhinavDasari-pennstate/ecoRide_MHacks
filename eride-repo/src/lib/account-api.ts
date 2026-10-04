import { useQuery } from "@tanstack/react-query";
import type { ApiMatch, ApiTrip, ApiVehicle, ImpactTotals } from "./backend";

export type AccountRole = "rider" | "owner" | "buyer";
export type SessionUser = { id: number; name: string; email: string; role: AccountRole };
export type AccountTrip = ApiTrip & { role: "driver" | "passenger"; party_size: number };
export type AccountVehicle = ApiVehicle & {
  seats: number;
  range_mi: number;
  lat: number;
  lng: number;
  efficiency_source?: string;
};
export type DataEarnings = {
  trips: number;
  cents: number;
  per_trip_cents: number;
  simulated: boolean;
  basis: string;
};
export type AccountDashboard = {
  user: { id: number; name: string; roles: string[] };
  trips: AccountTrip[];
  vehicles: AccountVehicle[];
  matches: ApiMatch[];
  impact: ImpactTotals;
  data_earnings?: DataEarnings;
};
export type CampusImpact = ImpactTotals & { matches: number; ev_share: number };

export class AccountError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function accountRequest<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const base = (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "/api";
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: options.method ?? "GET",
      credentials: "include",
      cache: "no-store",
      headers: options.body === undefined ? {} : { "Content-Type": "application/json" },
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      signal: AbortSignal.timeout(65000),
    });
  } catch {
    throw new AccountError("We couldn't connect. Check your connection and try again.", 0);
  }
  const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
      window.dispatchEvent(new Event("eride-session-expired"));
    }
    throw new AccountError(
      typeof payload?.detail === "string"
        ? payload.detail
        : response.status === 401
          ? "Your session has ended. Please sign in again."
          : "That request couldn't be completed. Please try again.",
      response.status,
    );
  }
  return payload as T;
}

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: () => accountRequest<{ user: SessionUser | null }>("/auth/me"),
    staleTime: 30_000,
    refetchInterval: 30_000,
    retry: false,
  });
}

export function useAccountDashboard(userId: number | undefined) {
  return useQuery({
    queryKey: ["dashboard", userId],
    queryFn: () => accountRequest<AccountDashboard>(`/users/${userId}/dashboard`),
    enabled: userId !== undefined,
    refetchInterval: 5000,
    retry: false,
  });
}

export type RideNotification = {
  id: number;
  ts: string;
  notice: "proposed" | "confirmed" | "vehicle_changed";
  text: string;
  delivered: "sms" | "in_app" | null;
  match_id: number | null;
};

export function useNotifications(enabled: boolean) {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => accountRequest<{ notifications: RideNotification[] }>("/me/notifications"),
    enabled,
    refetchInterval: 5000,
    retry: false,
  });
}

export type ModelRun = {
  name: string;
  kind: string;
  trained_at: string;
  library: string;
  dataset_rows: number;
  random_seed: number;
  features: string[];
  metrics: Record<string, number | string>;
  notes: string;
};
export type TripScore = {
  tripId: string;
  driverId: string;
  startedAt: string;
  miles: number;
  features: Record<string, number | boolean>;
  anomalyScore: number | null;
  anomalyFlagged: boolean | null;
  riskProbability: number | null;
  predictedKwhPerMi: number | null;
  actualKwhPerMi: number | null;
  scoredBy: "fixture" | "runtime" | "unscored";
  source?: "fixture" | "booking";
  matchId?: number | null;
};
export type DriverRisk = {
  driverId: string;
  trips: number;
  riskScore: number;
  meanProbability: number;
};
export type BuyerInsights = {
  simulated: boolean;
  validated: boolean;
  disclaimer: string;
  runs: ModelRun[];
  tripScores: TripScore[];
  driverRisk: DriverRisk[];
  liveBookingTrips: number;
  voidedBookingTrips: number;
};

export function useBuyerInsights(enabled: boolean) {
  return useQuery({
    queryKey: ["buyer-insights"],
    queryFn: () => accountRequest<BuyerInsights>("/buyer/insights"),
    enabled,
    retry: false,
  });
}

export function useCampusImpact() {
  return useQuery({
    queryKey: ["impact"],
    queryFn: () => accountRequest<CampusImpact>("/impact"),
    staleTime: 30_000,
    refetchInterval: 30_000,
    retry: false,
  });
}

export function useVoiceAgent() {
  return useQuery({
    queryKey: ["voice-agent"],
    queryFn: () => accountRequest<{ agent_id: string; phone: string }>("/voice/agent"),
    staleTime: Infinity,
    retry: false,
  });
}

export function accountHome(user: SessionUser): "/" | "/owner" | "/buyer" {
  return user.role === "buyer" ? "/buyer" : user.role === "owner" ? "/owner" : "/";
}

export function allowedPage(path: string, role: AccountRole): boolean {
  if (path === "/buyer" || path.startsWith("/buyer/")) return role === "buyer";
  if (path === "/owner" || path.startsWith("/owner/")) return role === "owner";
  if (path === "/profile" || path.startsWith("/trip/")) return role === "rider" || role === "owner";
  return true;
}
