import { useQuery } from "@tanstack/react-query";
import type { ApiMatch, ApiTrip, ApiVehicle } from "./backend";

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
export type AccountDashboard = {
  user: { id: number; name: string; roles: string[] };
  trips: AccountTrip[];
  vehicles: AccountVehicle[];
  matches: ApiMatch[];
};

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

export function accountHome(user: SessionUser): "/" | "/owner" | "/buyer" {
  return user.role === "buyer" ? "/buyer" : user.role === "owner" ? "/owner" : "/";
}

export function allowedPage(path: string, role: AccountRole): boolean {
  if (path === "/buyer" || path.startsWith("/buyer/")) return role === "buyer";
  if (path === "/owner" || path.startsWith("/owner/")) return role === "owner";
  if (path === "/profile" || path.startsWith("/trip/")) return role === "rider" || role === "owner";
  return true;
}
