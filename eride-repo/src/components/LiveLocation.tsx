import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LocateFixed, MapPin } from "lucide-react";
import { accountRequest } from "@/lib/account-api";
import type { ApiMatch } from "@/lib/backend";

type Point = { lat: number; lng: number };
type Person = Point & {
  user_id: number;
  name: string;
  role: string;
  accuracy_m: number | null;
  updated_at: string;
};

const POLL_MS = 5000;
const SEND_MS = 5000;
const MAP_KEY = import.meta.env["VITE_GOOGLE_MAPS_BROWSER_KEY"] as string | undefined;

// Only the parts of the Google Maps JS API used here; avoids a types dependency.
type GMap = { fitBounds(bounds: unknown, padding?: number): void; setZoom(zoom: number): void };
type GMarker = { position: Point; map: GMap | null; title: string };
type Maps = {
  Map: new (el: HTMLElement, options: object) => GMap;
  LatLngBounds: new () => { extend(point: Point): void };
  AdvancedMarkerElement: new (options: object) => GMarker;
};

let mapsLoading: Promise<Maps> | null = null;
function loadMaps(key: string): Promise<Maps> {
  mapsLoading ??= new Promise<Maps>((resolve, reject) => {
    const w = window as unknown as Record<string, unknown>;
    w["__erideMapsReady"] = async () => {
      const google = w["google"] as {
        maps: { importLibrary(name: string): Promise<Record<string, unknown>> };
      };
      const [maps, marker, core] = await Promise.all(
        ["maps", "marker", "core"].map((name) => google.maps.importLibrary(name)),
      );
      resolve({ ...core, ...maps, ...marker } as unknown as Maps);
    };
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&loading=async&callback=__erideMapsReady`;
    script.async = true;
    script.onerror = () => {
      mapsLoading = null;
      reject(new Error("Google Maps could not load."));
    };
    document.head.append(script);
  });
  return mapsLoading;
}

function pin(label: string, you: boolean) {
  const el = document.createElement("span");
  el.textContent = label.slice(0, 1).toUpperCase();
  el.style.cssText = `display:grid;place-items:center;width:34px;height:34px;border-radius:999px;font:600 14px system-ui;color:#fff;border:3px solid #fff;box-shadow:0 2px 6px rgb(0 0 0/.35);background:${you ? "#2563eb" : "#15803d"}`;
  return el;
}

function ago(iso: string) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 60 ? "just now" : `${Math.round(s / 60)} min ago`;
}

function LocationMap({ people }: { people: (Person & { you: boolean })[] }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<{ maps: Maps; map: GMap; markers: Map<number, GMarker> } | null>(null);
  const [failed, setFailed] = useState("");
  const [ready, setReady] = useState(false);
  const fitted = useRef(0);
  const count = people.length;

  useEffect(() => {
    if (!MAP_KEY || !el.current || map.current) return;
    let cancelled = false;
    loadMaps(MAP_KEY)
      .then((maps) => {
        if (cancelled || !el.current) return;
        const created = new maps.Map(el.current, {
          center: { lat: 42.2808, lng: -83.743 },
          zoom: 13,
          mapId: "DEMO_MAP_ID",
          disableDefaultUI: true,
          zoomControl: true,
        });
        map.current = { maps, map: created, markers: new Map() };
        setReady(true);
      })
      .catch((error: unknown) =>
        setFailed(error instanceof Error ? error.message : "Google Maps could not load."),
      );
    return () => {
      cancelled = true;
    };
  }, []);

  // Move markers in place every poll; only refit the view when someone joins or leaves.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const seen = new Set<number>();
    for (const p of people) {
      seen.add(p.user_id);
      const existing = m.markers.get(p.user_id);
      if (existing) existing.position = { lat: p.lat, lng: p.lng };
      else
        m.markers.set(
          p.user_id,
          new m.maps.AdvancedMarkerElement({
            map: m.map,
            position: { lat: p.lat, lng: p.lng },
            title: p.you ? "You" : p.name,
            content: pin(p.you ? "You" : p.name, p.you),
          }),
        );
    }
    for (const [id, marker] of m.markers)
      if (!seen.has(id)) {
        marker.map = null;
        m.markers.delete(id);
      }
    if (count && count !== fitted.current) {
      const bounds = new m.maps.LatLngBounds();
      people.forEach((p) => bounds.extend(p));
      m.map.fitBounds(bounds, 48);
      if (count === 1) m.map.setZoom(15);
      fitted.current = count;
    }
  }, [people, count, ready]);

  if (!MAP_KEY || failed) return failed ? <p className="account-error text-sm">{failed}</p> : null;
  return (
    <div
      ref={el}
      role="img"
      aria-label="Map of live locations"
      className="h-72 w-full overflow-hidden rounded-2xl bg-secondary"
    />
  );
}

export function LiveLocation({
  match,
  userId,
  travelRole,
}: {
  match: ApiMatch;
  userId: number;
  /** null for the vehicle owner, who sees the driver but isn't in the car. */
  travelRole: "driver" | "passenger" | null;
}) {
  const [sharing, setSharing] = useState(false);
  const [mine, setMine] = useState<Point | null>(null);
  const [geoError, setGeoError] = useState("");
  const lastSent = useRef(0);
  const locations = useQuery({
    queryKey: ["locations", match.id],
    queryFn: () => accountRequest<{ locations: Person[] }>(`/matches/${match.id}/locations`),
    refetchInterval: POLL_MS,
    retry: false,
  });

  useEffect(() => {
    if (!sharing) return;
    if (!("geolocation" in navigator)) {
      setGeoError("This browser can't share its location.");
      setSharing(false);
      return;
    }
    lastSent.current = 0;
    const watch = navigator.geolocation.watchPosition(
      (position) => {
        const point = { lat: position.coords.latitude, lng: position.coords.longitude };
        setMine(point);
        setGeoError("");
        if (Date.now() - lastSent.current < SEND_MS) return;
        lastSent.current = Date.now();
        accountRequest(`/matches/${match.id}/location`, {
          method: "POST",
          body: { ...point, accuracy_m: Math.round(position.coords.accuracy) },
        }).catch((error: unknown) =>
          setGeoError(error instanceof Error ? error.message : "Your location couldn't be sent."),
        );
      },
      (error) => {
        setGeoError(
          error.code === error.PERMISSION_DENIED
            ? "Location access is blocked. Allow it in your browser's site settings, then try again."
            : "Your location isn't available right now.",
        );
        if (error.code === error.PERMISSION_DENIED) setSharing(false);
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    );
    return () => navigator.geolocation.clearWatch(watch);
  }, [sharing, match.id]);

  const others = (locations.data?.locations ?? []).filter((p) => p.user_id !== userId);
  const people = [
    ...others.map((p) => ({ ...p, you: false })),
    ...(sharing && mine
      ? [
          {
            ...mine,
            user_id: userId,
            name: "You",
            role: travelRole ?? "",
            accuracy_m: null,
            updated_at: new Date().toISOString(),
            you: true,
          },
        ]
      : []),
  ];
  const watching = travelRole === "driver" ? "your group" : "your driver";

  return (
    <section className="account-panel" aria-labelledby={`live-${match.id}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={`live-${match.id}`} className="text-xl font-semibold">
            Live location
          </h2>
          <p className="account-muted mt-1 text-sm">
            {travelRole === "driver"
              ? "You can see your passengers. Your passengers and the vehicle owner can see you."
              : travelRole === "passenger"
                ? "You can see your driver. Only your driver can see you."
                : "You can see the driver of your vehicle while the trip is underway."}
          </p>
        </div>
        {travelRole && (
          <button
            className={sharing ? "account-secondary" : "account-button"}
            aria-pressed={sharing}
            onClick={() => setSharing((on) => !on)}
          >
            <LocateFixed className="size-4" />
            {sharing ? "Stop sharing" : "Share my location"}
          </button>
        )}
      </div>
      {geoError && (
        <p role="alert" className="account-error mb-4 text-sm">
          {geoError}
        </p>
      )}
      <LocationMap people={people} />
      <ul className="mt-4 divide-y divide-border" aria-live="polite">
        {others.length === 0 ? (
          <li className="account-muted py-3 text-sm">
            {locations.error
              ? locations.error.message
              : `Waiting for ${watching} to share their location.`}
          </li>
        ) : (
          others.map((p) => (
            <li key={p.user_id} className="flex items-center justify-between gap-3 py-3 text-sm">
              <span className="flex items-center gap-2">
                <MapPin className="size-4 text-primary" />
                <span className="font-semibold">{p.name}</span>
                <span className="account-muted">{p.role === "driver" ? "Driver" : "Rider"}</span>
              </span>
              <a
                className="account-muted underline underline-offset-4"
                href={`https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}`}
                target="_blank"
                rel="noreferrer"
              >
                Updated {ago(p.updated_at)}
              </a>
            </li>
          ))
        )}
      </ul>
      {sharing && (
        <p className="account-muted mt-3 text-xs">
          Sharing while this page is open. Your phone may pause it when the screen locks.
        </p>
      )}
    </section>
  );
}
