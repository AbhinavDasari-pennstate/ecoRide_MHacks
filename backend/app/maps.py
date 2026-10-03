"""Road distances and routes from the Google Routes API, with a process cache, the
route_cache table, and a haversine * ROAD_FACTOR estimate when Google is unavailable.
Nothing here raises: a failed call just means an estimate. No key = no network at all."""
import copy
import logging

import httpx
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import config
from app.core import LatLng, estimate_dist

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs full URLs at INFO; geocode URLs carry the key

MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
MATRIX_MASK = "originIndex,destinationIndex,distanceMeters,duration,condition,status"
ROUTES_MASK = ("routes.optimizedIntermediateWaypointIndex,routes.distanceMeters,routes.duration,"
               "routes.polyline.encodedPolyline,routes.legs.distanceMeters,routes.legs.duration")
BLOCK = 25                 # 25 x 25 = 625, the matrix element limit without traffic-aware routing
M_PER_MI = 1609.344

_http = httpx.Client(timeout=5.0)   # tests swap this for an httpx.MockTransport client
# ponytail: unbounded process dicts and no TTL; road distances barely change (truncate route_cache to refresh)
_dist_mem: dict[str, float] = {}    # pair key -> road miles (Google results only)
_route_mem: dict[str, dict] = {}    # route key -> {polyline, distance_mi, duration_min, legs, order}

UPSERT = """insert into route_cache (key, distance_mi, duration_min, polyline, payload) values (%s, %s, %s, %s, %s)
on conflict (key) do update set distance_mi = excluded.distance_mi, duration_min = excluded.duration_min,
  polyline = excluded.polyline, payload = excluded.payload, fetched_at = now()"""


def _pt(p: LatLng) -> str:
    return f"{p[0]:.4f},{p[1]:.4f}"


def _pair_key(a: LatLng, b: LatLng) -> str:
    return f"{_pt(a)}>{_pt(b)}|DRIVE"


def _wp(p: LatLng) -> dict:
    return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}


def _mins(duration) -> float:
    return float(str(duration or "0s").rstrip("s")) / 60     # Google durations look like "754s"


def _post(url: str, body: dict, mask: str):
    r = _http.post(url, json=body, headers={"X-Goog-Api-Key": config.MAPS_SERVER_KEY, "X-Goog-FieldMask": mask})
    r.raise_for_status()
    return r.json()


def _why(e: Exception) -> str:
    """Log-safe summary: type, HTTP status and Google's message. Never the request URL."""
    if not isinstance(e, httpx.HTTPStatusError):
        return type(e).__name__
    try:
        msg = e.response.json()["error"]["message"]
    except Exception:
        msg = ""
    out = f"HTTP {e.response.status_code} {msg}"
    return out.replace(config.MAPS_SERVER_KEY, "***") if config.MAPS_SERVER_KEY else out


def encode_polyline(points: list[LatLng]) -> str:
    """Google's encoded polyline algorithm (1e-5 degree precision)."""
    out, prev = [], (0, 0)
    for lat, lng in points:
        cur = (round(lat * 1e5), round(lng * 1e5))
        for d in (cur[0] - prev[0], cur[1] - prev[1]):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev = cur
    return "".join(out)


def _estimate_route(pts: list[LatLng], n_stops: int) -> dict:
    miles = [estimate_dist(a, b) for a, b in zip(pts, pts[1:])]
    return {
        "polyline": encode_polyline(pts),           # straight segments, so the map still draws something
        "distance_mi": round(sum(miles), 2),
        "duration_min": round(sum(miles) / config.AVG_SPEED_MPH * 60, 1),
        "legs": [{"distance_mi": round(m, 2), "duration_min": round(m / config.AVG_SPEED_MPH * 60, 1)} for m in miles],
        "order": list(range(n_stops)),              # core already ordered the pickups
        "source": "estimate",
    }


class Maps:
    """One per planning run. c = psycopg connection for route_cache (None = process memory only)."""

    def __init__(self, c=None):
        self.c = c
        # ponytail: the first failed call turns the network off for this instance, so a dead API costs one timeout
        self.live = bool(config.MAPS_SERVER_KEY)
        self._est: dict[str, float] = {}      # pairs this instance had to estimate (never retried)
        self._served: set[str] = set()        # sources of every distance dist() returned

    @property
    def source(self) -> str:
        if self._served == {"google_routes"}:
            return "google_routes"
        return "mixed" if len(self._served) > 1 else "estimate"

    def dist(self, a: LatLng, b: LatLng) -> float:
        if _pt(a) == _pt(b):
            return 0.0
        k = _pair_key(a, b)
        if config.MAPS_SERVER_KEY and k not in self._est:
            if k not in _dist_mem:
                self._load([k])
            if k not in _dist_mem and self.live:
                self._matrix([a], [b])
            if k in _dist_mem:
                self._served.add("google_routes")
                return _dist_mem[k]
        self._served.add("estimate")
        return self._est.setdefault(k, estimate_dist(a, b))

    def prefetch(self, points: list[LatLng]) -> None:
        if not self.live:
            return
        pts = list({_pt(p): p for p in points}.values())

        def missing(srcs, dsts):
            return [_pair_key(a, b) for a in srcs for b in dsts if _pt(a) != _pt(b) and _pair_key(a, b) not in _dist_mem]

        self._load(missing(pts, pts))
        # ponytail: fetches whole 25x25 blocks that have any gap, even if most of the block is cached
        for i in range(0, len(pts), BLOCK):
            for j in range(0, len(pts), BLOCK):
                if self.live and missing(pts[i:i + BLOCK], pts[j:j + BLOCK]):
                    self._matrix(pts[i:i + BLOCK], pts[j:j + BLOCK])

    def route(self, origin: LatLng, stops: list[LatLng], dest: LatLng, optimize: bool = True) -> dict:
        stops = list(stops)
        pts = [origin, *stops, dest]
        k = "route|" + ";".join(map(_pt, pts)) + "|DRIVE" + ("|opt" if optimize else "")
        hit = None
        if config.MAPS_SERVER_KEY:
            hit = _route_mem.get(k) or self._load_route(k)
            if hit is None and self.live:
                hit = self._compute_route(k, origin, stops, dest, optimize)
        if hit is None:
            return _estimate_route(pts, len(stops))
        return {**copy.deepcopy(hit), "source": "google_routes"}

    # ------------------------------------------------------------ Google calls

    def _matrix(self, origins: list[LatLng], dests: list[LatLng]) -> None:
        body = {"origins": [{"waypoint": _wp(p)} for p in origins],
                "destinations": [{"waypoint": _wp(p)} for p in dests],
                "travelMode": "DRIVE"}       # no routingPreference = TRAFFIC_UNAWARE: cacheable, 625-element limit
        try:
            rows = []
            for e in _post(MATRIX_URL, body, MATRIX_MASK):
                # proto3 JSON omits zero values, so index 0 and 0 m can be missing
                a, b = origins[e.get("originIndex", 0)], dests[e.get("destinationIndex", 0)]
                if e.get("condition") != "ROUTE_EXISTS" or e.get("status", {}).get("code") or _pt(a) == _pt(b):
                    continue
                k = _pair_key(a, b)
                _dist_mem[k] = e.get("distanceMeters", 0) / M_PER_MI
                rows.append((k, _dist_mem[k], _mins(e.get("duration")), None, None))
        except Exception as e:
            self.live = False
            log.warning("Routes matrix failed (%s); using estimates for the rest of this run", _why(e))
            return
        for a in origins:          # no route between them: estimate, and don't ask again
            for b in dests:
                if _pt(a) != _pt(b) and _pair_key(a, b) not in _dist_mem:
                    self._est.setdefault(_pair_key(a, b), estimate_dist(a, b))
        self._db(UPSERT, rows, many=True)

    def _compute_route(self, k, origin, stops, dest, optimize) -> dict | None:
        body = {"origin": _wp(origin), "destination": _wp(dest), "intermediates": [_wp(s) for s in stops],
                "travelMode": "DRIVE", "optimizeWaypointOrder": optimize and len(stops) > 1}
        try:
            r = _post(ROUTES_URL, body, ROUTES_MASK)["routes"][0]
            order = r.get("optimizedIntermediateWaypointIndex") or []
            if sorted(order) != list(range(len(stops))):
                order = list(range(len(stops)))
            hit = {
                "polyline": r["polyline"]["encodedPolyline"],
                "distance_mi": round(r.get("distanceMeters", 0) / M_PER_MI, 2),
                "duration_min": round(_mins(r.get("duration")), 1),
                "legs": [{"distance_mi": round(leg.get("distanceMeters", 0) / M_PER_MI, 2),
                          "duration_min": round(_mins(leg.get("duration")), 1)} for leg in r.get("legs", [])],
                "order": order,
            }
        except Exception as e:
            self.live = False
            log.warning("Routes computeRoutes failed (%s); using an estimate", _why(e))
            return None
        _route_mem[k] = hit
        self._db(UPSERT, [(k, hit["distance_mi"], hit["duration_min"], hit["polyline"],
                           Jsonb({"order": hit["order"], "legs": hit["legs"]}))], many=True)
        return hit

    # ------------------------------------------------------------ route_cache

    def _load(self, keys: list[str]) -> None:
        if keys:
            for row in self._db("select key, distance_mi from route_cache where key = any(%s)", (keys,)):
                _dist_mem[row["key"]] = row["distance_mi"]

    def _load_route(self, k: str) -> dict | None:
        rows = self._db("select distance_mi, duration_min, polyline, payload from route_cache where key = %s", (k,))
        if not rows or not rows[0]["polyline"] or not rows[0]["payload"]:
            return None
        r = rows[0]
        _route_mem[k] = {"polyline": r["polyline"], "distance_mi": r["distance_mi"], "duration_min": r["duration_min"],
                         "legs": r["payload"]["legs"], "order": r["payload"]["order"]}
        return _route_mem[k]

    def _db(self, sql: str, params, many: bool = False) -> list[dict]:
        """route_cache I/O in a savepoint: a failure is logged and swallowed and never aborts
        the caller's transaction."""
        if self.c is None or (many and not params):
            return []
        try:
            with self.c.transaction(), self.c.cursor(row_factory=dict_row) as cur:
                if many:
                    cur.executemany(sql, params)
                    return []
                cur.execute(sql, params)
                return cur.fetchall()
        except Exception as e:
            log.warning("route_cache access failed (%s); continuing without it", type(e).__name__)
            return []


def geocode(query: str, near: LatLng = config.ANN_ARBOR) -> dict | None:
    """First Geocoding API result biased to a ~20 mi box around `near`, or None."""
    if not config.MAPS_SERVER_KEY or not query:
        return None
    lat, lng = near
    try:
        r = _http.get(GEOCODE_URL, params={"address": query, "key": config.MAPS_SERVER_KEY, "region": "us",
                                           "bounds": f"{lat - 0.15},{lng - 0.2}|{lat + 0.15},{lng + 0.2}"})
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            log.info("geocode returned %s", data.get("status"))
            return None
        g = data["results"][0]
        return {"lat": g["geometry"]["location"]["lat"], "lng": g["geometry"]["location"]["lng"],
                "place_id": g.get("place_id"), "formatted_address": g.get("formatted_address")}
    except Exception as e:
        log.warning("geocode failed (%s)", _why(e))
        return None
