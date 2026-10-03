"""Reset the database to the demo scenario: schema, 7 users, 4 vehicles, no trips.
Idempotent; ids are deterministic (TRUNCATE ... RESTART IDENTITY). Keeps route_cache unless --clear-cache.
    python scripts/seed.py [--clear-cache]"""
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, core, db, maps  # noqa: E402

TZ = ZoneInfo(config.TIMEZONE)
# Meijer #64; OpenStreetMap building coords, used when geocoding is unavailable
MEIJER = {"dest_name": "Meijer (Ann Arbor-Saline Rd)", "dest_place_id": None,
          "dest_lat": 42.2394, "dest_lng": -83.7660}

# (name, roles, home lat, lng, rating); ids 1-7 in this order
USERS = [
    ("Alex", ["driver"], 42.2780, -83.7400, 4.8),       # drives, has no car
    ("Maya", ["passenger"], 42.2800, -83.7330, 4.9),
    ("Jordan", ["passenger"], 42.2720, -83.7500, 4.7),
    ("Sam", ["owner"], 42.2820, -83.7260, 4.9),          # Tesla
    ("Priya", ["owner"], 42.2740, -83.7330, 4.8),        # Civic: closer to Alex and cheaper than the Tesla
    ("Diego", ["owner"], 42.2620, -83.7180, 4.6),        # RAV4
    ("Riley", ["owner"], 42.2650, -83.7500, 4.7),        # Leaf
]
# (owner_id, make_model, fuel, efficiency kWh/mi or mpg, range_mi, cents/hour, local avail hours); parked at the
# owner's home. Specs: fueleconomy.gov (2026 Model 3 RWD, 2025 Leaf S 40 kWh, 2025 Civic 2.0L, 2025 RAV4 2.5L FWD)
VEHICLES = [
    (4, "Tesla Model 3", "ev", 0.243, 321, 800, (time(13), time(17))),
    (5, "Honda Civic", "gas", 36, 446, 700, (time(8), time(22))),
    (6, "Toyota RAV4", "gas", 30, 435, 1000, (time(8), time(22))),
    (7, "Nissan Leaf", "ev", 0.304, 149, 900, (time(13, 30), time(17))),
]


def saturday() -> date:
    """The upcoming Saturday, strictly after today (campus time)."""
    today = datetime.now(TZ).date()
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def _utc(d: date, t: time) -> datetime:
    return datetime.combine(d, t, TZ).astimezone(timezone.utc)


def scenario_window() -> tuple[datetime, datetime]:
    """Departure window for every scenario trip: Saturday 13:45-14:30 local, as UTC."""
    d = saturday()
    return _utc(d, time(13, 45)), _utc(d, time(14, 30))


def destination() -> dict:
    g = maps.geocode("Meijer, Ann Arbor-Saline Rd, Ann Arbor, MI")
    # ponytail: trust the geocoder only if it lands within a mile of the known store
    if not g or core.haversine_mi((g["lat"], g["lng"]), (MEIJER["dest_lat"], MEIJER["dest_lng"])) > 1:
        return dict(MEIJER)
    return {**MEIJER, "dest_place_id": g["place_id"], "dest_lat": g["lat"], "dest_lng": g["lng"]}


def reset(clear_cache: bool = False) -> dict:
    db.apply_schema()
    sat, dest = saturday(), destination()
    tables = "users, vehicles, trips, matches, match_members, bookings, agent_runs, events" + (", route_cache" if clear_cache else "")
    with db.conn() as c:
        c.execute(f"truncate {tables} restart identity cascade")
        for n, (name, roles, lat, lng, rating) in enumerate(USERS, 1):
            c.execute("insert into users (name, phone, roles, home_lat, home_lng, verified, rating)"
                      " values (%s, %s, %s, %s, %s, true, %s)", (name, f"555-01{n:02d}", roles, lat, lng, rating))
        for owner, model, fuel, eff, rng, cents, (t0, t1) in VEHICLES:
            _, _, lat, lng, _ = USERS[owner - 1]
            c.execute("insert into vehicles (owner_id, make_model, fuel_type, seats, range_mi, efficiency,"
                      " price_per_hour_cents, lat, lng, avail_start, avail_end) values (%s, %s, %s, 5, %s, %s, %s, %s, %s, %s, %s)",
                      (owner, model, fuel, rng, eff, cents, lat, lng, _utc(sat, t0), _utc(sat, t1)))
        if config.MAPS_SERVER_KEY:   # pre-warm route_cache so the demo doesn't wait on Google
            m = maps.Maps(c)
            pts = [(u[2], u[3]) for u in USERS] + [(dest["dest_lat"], dest["dest_lng"])]
            m.prefetch(pts)
            m.route(pts[0], [pts[1], pts[2]], pts[-1])    # Alex -> Maya -> Jordan -> Meijer
    start, end = scenario_window()
    return {"users": {u[0]: n for n, u in enumerate(USERS, 1)},
            "vehicles": {v[1]: n for n, v in enumerate(VEHICLES, 1)},
            "destination": dest, "window_start": start, "window_end": end}


if __name__ == "__main__":
    out = reset(clear_cache="--clear-cache" in sys.argv)
    print(f"seeded {len(out['users'])} users, {len(out['vehicles'])} vehicles")
    print(f"destination: {out['destination']['dest_name']} ({out['destination']['dest_lat']:.4f}, {out['destination']['dest_lng']:.4f})")
    print(f"scenario window: {out['window_start'].astimezone(TZ):%a %Y-%m-%d %H:%M}-{out['window_end'].astimezone(TZ):%H:%M} {config.TIMEZONE}")
    print("route cache:", "pre-warmed from Google" if config.MAPS_SERVER_KEY else "skipped (no MAPS_SERVER_KEY, estimates only)")
