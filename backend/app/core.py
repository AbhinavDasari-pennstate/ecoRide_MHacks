"""Pure planning logic: models, plan completion (vehicle pick + pickup order), validator,
fallback planner, pricing and impact. No database or network access: distances come in
through `Ctx.dist(a, b) -> road miles`, so all of this is unit-testable offline."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app import config as C

LatLng = tuple[float, float]
Dist = Callable[[LatLng, LatLng], float]


# ---------------------------------------------------------------- models

class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Trip(_Row):
    id: int
    user_id: int
    role: str                      # driver | passenger
    origin_lat: float
    origin_lng: float
    dest_name: str = ""
    dest_lat: float
    dest_lng: float
    window_start: datetime
    window_end: datetime
    party_size: int = 1
    max_detour_mi: float = 2.0
    needs_vehicle: bool = False
    status: str = "open"

    @property
    def origin(self) -> LatLng:
        return (self.origin_lat, self.origin_lng)

    @property
    def dest(self) -> LatLng:
        return (self.dest_lat, self.dest_lng)


class Vehicle(_Row):
    id: int
    owner_id: Optional[int] = None
    make_model: str
    fuel_type: str                 # ev | gas
    seats: int                     # total occupants incl. driver
    range_mi: float
    efficiency: float              # kWh/mi (ev) or mpg (gas)
    price_per_hour_cents: int
    lat: float
    lng: float
    avail_start: datetime
    avail_end: datetime
    active: bool = True
    efficiency_source: str = "Owner-supplied estimate; not independently verified"

    @property
    def loc(self) -> LatLng:
        return (self.lat, self.lng)

    @property
    def label(self) -> str:
        return f"{self.make_model} ({'EV' if self.fuel_type == 'ev' else 'gas'})"


class Booking(_Row):
    id: int = 0
    match_id: int = 0
    vehicle_id: int
    start_ts: datetime
    end_ts: datetime
    status: str = "requested"


class Group(BaseModel):
    driver_trip_id: int
    passenger_trip_ids: list[int] = []
    vehicle_id: Optional[int] = None     # null = driver brings own car (or code fills it in complete())
    pickup_order: list[int] = []         # empty = code fills it in complete()
    depart_time: datetime
    rationale: list[str] = []            # short reasons, no numbers

    @field_validator("depart_time")
    @classmethod
    def _utc(cls, t: datetime) -> datetime:
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)   # Gemini sometimes drops the "Z"


class Unassigned(BaseModel):
    trip_id: int
    reason: str


class Plan(BaseModel):
    groups: list[Group] = []
    unassigned: list[Unassigned] = []


@dataclass
class Ctx:
    """Everything a plan is checked against. The caller decides scope:
    `trips` = trips being planned (open, plus members of matches being replanned);
    `bookings` = active bookings, EXCLUDING those of matches being replanned."""
    trips: dict[int, Trip]
    vehicles: dict[int, Vehicle]
    bookings: list[Booking] = field(default_factory=list)
    dist: Dist = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.dist is None:
            self.dist = estimate_dist


# ---------------------------------------------------------------- distance

def haversine_mi(a: LatLng, b: LatLng) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def estimate_dist(a: LatLng, b: LatLng) -> float:
    """Fallback road distance when Maps is unavailable."""
    return haversine_mi(a, b) * C.ROAD_FACTOR


def route_one_way(ctx: Ctx, driver: Trip, pickups: list[Trip]) -> float:
    pts = [driver.origin] + [p.origin for p in pickups] + [driver.dest]
    return sum(ctx.dist(a, b) for a, b in zip(pts, pts[1:]))


def solo_mi(ctx: Ctx, t: Trip) -> float:
    return ctx.dist(t.origin, t.dest)


def nearest_neighbor_order(ctx: Ctx, driver: Trip, pickups: list[Trip]) -> list[int]:
    # ponytail: greedy nearest neighbor, fine for <= 4 pickups; Maps optimizeWaypointOrder refines the real route
    here, left, order = driver.origin, list(pickups), []
    while left:
        nxt = min(left, key=lambda p: (ctx.dist(here, p.origin), p.id))
        order.append(nxt.id)
        left.remove(nxt)
        here = nxt.origin
    return order


def added_detours(ctx: Ctx, driver: Trip, ordered: list[Trip]) -> dict[int, float]:
    """Miles each passenger adds to the driver's one-way route."""
    full = route_one_way(ctx, driver, ordered)
    return {p.id: full - route_one_way(ctx, driver, [q for q in ordered if q.id != p.id]) for p in ordered}


def detour_limit(ctx: Ctx, p: Trip) -> float:
    return min(p.max_detour_mi, solo_mi(ctx, p))


# ---------------------------------------------------------------- miles, time, money, CO2

def group_size(members: list[Trip]) -> int:
    return sum(t.party_size for t in members)


def shared_miles(ctx: Ctx, driver: Trip, ordered: list[Trip], vehicle: Optional[Vehicle]) -> dict:
    """Deadhead both ways (vehicle <-> driver) plus the pickup route round trip."""
    deadhead = 2 * ctx.dist(vehicle.loc, driver.origin) if vehicle else 0.0
    route = 2 * route_one_way(ctx, driver, ordered)
    return {"deadhead_mi": deadhead, "route_mi": route, "shared_mi": deadhead + route}


def rental_hours(miles: float) -> float:
    raw = miles / C.AVG_SPEED_MPH + C.STOP_BUFFER_HOURS
    inc = C.RENTAL_INCREMENT_HOURS
    return math.ceil(raw / inc - 1e-9) * inc


def booking_window(depart: datetime, hours: float) -> tuple[datetime, datetime]:
    """Interval the vehicle must be free: rental time plus the availability buffer."""
    return depart, depart + timedelta(hours=hours, minutes=C.AVAIL_BUFFER_MIN)


def _fuel(vehicle: Optional[Vehicle]) -> tuple[str, float]:
    return (vehicle.fuel_type, vehicle.efficiency) if vehicle else ("gas", C.OWN_CAR_MPG)


def co2_kg(vehicle: Optional[Vehicle], miles: float) -> float:
    fuel, eff = _fuel(vehicle)
    if fuel == "ev":
        return miles * eff * C.GRID_KG_CO2_PER_KWH        # mi * kWh/mi * kg/kWh
    return miles / eff * C.GAS_KG_CO2_PER_GALLON          # mi / mpg * kg/gal


def energy_cents(vehicle: Optional[Vehicle], miles: float) -> int:
    fuel, eff = _fuel(vehicle)
    usd = miles * eff * C.ELECTRICITY_USD_PER_KWH if fuel == "ev" else miles / eff * C.GAS_USD_PER_GALLON
    return math.ceil(usd * 100 - 1e-9)


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def pricing(vehicle: Optional[Vehicle], miles: float, size: int) -> dict:
    """total_cost_cents = cost_per_person_cents * size exactly; the round-up is shown as rounding_cents."""
    hours = rental_hours(miles)
    rental = math.ceil(hours * vehicle.price_per_hour_cents) if vehicle else 0
    energy = energy_cents(vehicle, miles)
    raw = rental + energy
    per = ceil_div(raw, size)
    return {
        "rental_hours": hours, "rental_cents": rental, "energy_cents": energy,
        "raw_cost_cents": raw, "group_size": size,
        "cost_per_person_cents": per, "total_cost_cents": per * size, "rounding_cents": per * size - raw,
    }


def impact(ctx: Ctx, driver: Trip, ordered: list[Trip], vehicle: Optional[Vehicle],
           distance_source: str = "estimate") -> dict:
    """Shared trip vs. baseline where every trip is a separate gas-car round trip."""
    sm = shared_miles(ctx, driver, ordered, vehicle)
    baseline = sum(2 * solo_mi(ctx, t) for t in [driver] + ordered)
    kg_shared = co2_kg(vehicle, sm["shared_mi"])
    kg_base = baseline * C.BASELINE_KG_CO2_PER_MILE
    return {
        "shared_miles": round(sm["shared_mi"], 2),
        "deadhead_miles": round(sm["deadhead_mi"], 2),
        "route_miles": round(sm["route_mi"], 2),
        "baseline_miles": round(baseline, 2),
        "miles_avoided": round(baseline - sm["shared_mi"], 2),
        "kg_co2_shared": round(kg_shared, 2),
        "kg_co2_baseline": round(kg_base, 2),
        "kg_co2_avoided": round(kg_base - kg_shared, 2),
        "percent_reduction": round(100 * (kg_base - kg_shared) / kg_base, 1) if kg_base else 0.0,
        "assumptions": assumptions_for(distance_source),
    }


def assumptions_for(distance_source: str) -> dict:
    return {
        **C.assumptions(),
        "distance_source": distance_source,     # google_routes | estimate | mixed
        "baseline": "each traveler makes a separate gas-car round trip (solo or rideshare); transit is deliberately not the baseline",
        "shared_miles": "vehicle-to-driver deadhead both ways plus the pickup route round trip",
        "rental_hours": "round-trip miles / AVG_SPEED_MPH + STOP_BUFFER_HOURS, rounded up to RENTAL_INCREMENT_HOURS",
    }


# ---------------------------------------------------------------- vehicle feasibility and pick

def _fmt(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _overlaps(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


def vehicle_problems(ctx: Ctx, driver: Trip, ordered: list[Trip], depart: datetime,
                     v: Vehicle, extra: list[Booking] = ()) -> list[str]:
    """Hard-constraint failures for using vehicle v; empty list = feasible."""
    errs = []
    size = group_size([driver] + ordered)
    miles = shared_miles(ctx, driver, ordered, v)["shared_mi"]
    start, end = booking_window(depart, rental_hours(miles))
    if not v.active:
        errs.append(f"vehicle {v.id} ({v.make_model}) is not active")
    if size > v.seats:
        errs.append(f"vehicle {v.id} ({v.make_model}) has {v.seats} seats but the group has {size} people")
    if start < v.avail_start or end > v.avail_end:
        errs.append(f"vehicle {v.id} ({v.make_model}) is available {_fmt(v.avail_start)} to {_fmt(v.avail_end)} "
                    f"but the trip needs it {_fmt(start)} to {_fmt(end)}")
    for b in [*ctx.bookings, *extra]:
        if b.vehicle_id == v.id and b.status in ("requested", "approved") and _overlaps(start, end, b.start_ts, b.end_ts):
            errs.append(f"vehicle {v.id} ({v.make_model}) is already booked {_fmt(b.start_ts)} to {_fmt(b.end_ts)}"
                        + (f" (booking {b.id})" if b.id else " (by another group in this plan)"))
    usable = v.range_mi * (1 - C.EV_RANGE_RESERVE)
    if miles > usable:
        errs.append(f"vehicle {v.id} ({v.make_model}) round trip is {miles:.1f} mi, over its usable range of "
                    f"{usable:.0f} mi ({v.range_mi:.0f} mi minus a {C.EV_RANGE_RESERVE:.0%} reserve)")
    return errs


def vehicle_options(ctx: Ctx, driver: Trip, ordered: list[Trip], depart: datetime,
                    extra: list[Booking] = ()) -> list[dict]:
    """Every vehicle scored for this group, best first. The pick rule: lowest trip CO2
    (ties within CO2_TIE_KG go to the cheaper car), among feasible vehicles."""
    size = group_size([driver] + ordered)
    opts = []
    for v in ctx.vehicles.values():
        sm = shared_miles(ctx, driver, ordered, v)
        price = pricing(v, sm["shared_mi"], size)
        why_not = vehicle_problems(ctx, driver, ordered, depart, v, extra)
        opts.append({
            "vehicle_id": v.id, "make_model": v.make_model, "fuel_type": v.fuel_type,
            "deadhead_mi": round(sm["deadhead_mi"], 2), "shared_mi": round(sm["shared_mi"], 2),
            "kg_co2": round(co2_kg(v, sm["shared_mi"]), 2), "total_cost_cents": price["raw_cost_cents"],
            "feasible": not why_not, "why_not": why_not,
        })
    # tie = within CO2_TIE_KG of the cleanest feasible vehicle; the cheapest of those wins
    best = min((o["kg_co2"] for o in opts if o["feasible"]), default=0.0)
    tied = lambda o: o["feasible"] and o["kg_co2"] <= best + C.CO2_TIE_KG + 1e-9
    opts.sort(key=lambda o: (not o["feasible"], not tied(o), o["total_cost_cents"] if tied(o) else o["kg_co2"],
                             o["kg_co2"], o["deadhead_mi"], o["vehicle_id"]))
    return opts


def vehicle_reasons(options: list[dict], chosen_id: Optional[int]) -> list[str]:
    """Code-written reasons (numbers allowed: code computed them)."""
    chosen = next((o for o in options if o["vehicle_id"] == chosen_id), None)
    if not chosen:
        return []
    best = next((o for o in options if o["feasible"]), None)
    reason = "lowest CO2 of the feasible vehicles" if chosen is best else "selected feasible vehicle"
    out = [f"{chosen['make_model']} ({chosen['fuel_type'].upper() if chosen['fuel_type'] == 'ev' else 'gas'}) "
           f"chosen: {reason} at {chosen['kg_co2']:.1f} kg for this trip"]
    for o in options:
        if o is chosen:
            continue
        if o["feasible"]:
            out.append(f"{o['make_model']} ({o['fuel_type']}): {o['kg_co2']:.1f} kg CO2, "
                       f"{o['deadhead_mi']:.1f} mi deadhead, ${o['total_cost_cents'] / 100:.2f} total")
        else:
            out.append(f"{o['make_model']} ({o['fuel_type']}): not feasible: {o['why_not'][0]}")
    return out


# ---------------------------------------------------------------- completion

def complete(plan: Plan, ctx: Ctx) -> tuple[Plan, dict[int, list[dict]]]:
    """Fill what code owns: pickup_order (when empty) and vehicle_id (when null and the driver
    needs one). Groups with no feasible vehicle move to `unassigned`. Returns the completed plan
    and {driver_trip_id: vehicle_options}. Bad ids are left for validate() to report."""
    plan = plan.model_copy(deep=True)
    options: dict[int, list[dict]] = {}
    taken: list[Booking] = []
    kept: list[Group] = []
    for g in plan.groups:
        ids = [g.driver_trip_id, *g.passenger_trip_ids]
        if any(i not in ctx.trips for i in ids):
            kept.append(g)
            continue
        driver = ctx.trips[g.driver_trip_id]
        if not g.pickup_order:
            g.pickup_order = nearest_neighbor_order(ctx, driver, [ctx.trips[i] for i in g.passenger_trip_ids])
        ordered = [ctx.trips[i] for i in g.pickup_order if i in ctx.trips]
        if driver.needs_vehicle:
            opts = vehicle_options(ctx, driver, ordered, g.depart_time, taken)
            options[g.driver_trip_id] = opts
            if g.vehicle_id is None:
                if not opts or not opts[0]["feasible"]:
                    # a group that also breaks other rules (bad window, far destination) stays in the
                    # plan, so validate() names the real problem instead of it passing as "unassigned"
                    if any("needs a vehicle" not in e for e in validate(Plan(groups=[g]), ctx)):
                        kept.append(g)
                        continue
                    why = opts[0]["why_not"][0] if opts else "no vehicles listed"
                    plan.unassigned += [Unassigned(trip_id=i, reason=f"no feasible vehicle for this group ({why})") for i in ids]
                    continue
                g.vehicle_id = opts[0]["vehicle_id"]
        if g.vehicle_id in ctx.vehicles:
            v = ctx.vehicles[g.vehicle_id]
            start, end = booking_window(g.depart_time, rental_hours(shared_miles(ctx, driver, ordered, v)["shared_mi"]))
            taken.append(Booking(vehicle_id=v.id, start_ts=start, end_ts=end))
        kept.append(g)
    plan.groups = kept
    return plan, options


# ---------------------------------------------------------------- validator

def validate(plan: Plan, ctx: Ctx) -> list[str]:
    """Hard constraints on a (completed) plan. Each error names what is wrong and which id;
    they are fed back to Gemini verbatim on retry."""
    errs: list[str] = []
    where: dict[int, str] = {}
    taken: list[Booking] = []

    for n, g in enumerate(plan.groups, 1):
        tag = f"group {n} (driver trip {g.driver_trip_id})"
        ids = [g.driver_trip_id, *g.passenger_trip_ids]
        for i in ids:
            if i in where:
                errs.append(f"trip {i} appears in more than one group ({where[i]} and {tag})")
            where.setdefault(i, tag)
        if len(set(g.passenger_trip_ids)) != len(g.passenger_trip_ids):
            errs.append(f"{tag}: passenger_trip_ids {g.passenger_trip_ids} contains duplicates")
        missing = [i for i in ids if i not in ctx.trips]
        for i in missing:
            errs.append(f"{tag}: trip {i} does not exist or is not open for planning")
        if missing:
            continue

        driver = ctx.trips[g.driver_trip_id]
        passengers = [ctx.trips[i] for i in g.passenger_trip_ids]
        members = [driver, *passengers]
        if driver.role != "driver":
            errs.append(f"{tag}: trip {driver.id} is a {driver.role} trip and cannot be the driver")
        for p in passengers:
            if p.role != "passenger":
                errs.append(f"{tag}: trip {p.id} is a {p.role} trip and cannot ride as a passenger")
        for t in members:
            if t.status == "cancelled":
                errs.append(f"{tag}: trip {t.id} is cancelled")
            if not (t.window_start <= g.depart_time <= t.window_end):
                errs.append(f"{tag}: depart_time {_fmt(g.depart_time)} is outside trip {t.id}'s window "
                            f"{_fmt(t.window_start)} to {_fmt(t.window_end)}")
        for p in passengers:
            d = ctx.dist(p.dest, driver.dest)
            if d > C.DEST_RADIUS_MI:
                errs.append(f"{tag}: trip {p.id}'s destination is {d:.1f} mi from the driver's, over {C.DEST_RADIUS_MI} mi")

        order_ok = sorted(g.pickup_order) == sorted(g.passenger_trip_ids)
        if not order_ok:
            errs.append(f"{tag}: pickup_order {g.pickup_order} must contain exactly the passenger trip ids {sorted(g.passenger_trip_ids)}")
        ordered = [ctx.trips[i] for i in (g.pickup_order if order_ok else g.passenger_trip_ids)]
        for pid, extra in added_detours(ctx, driver, ordered).items():
            limit = detour_limit(ctx, ctx.trips[pid])
            if extra > limit + 1e-6:
                errs.append(f"{tag}: picking up trip {pid} adds {extra:.1f} mi of detour, over its limit of {limit:.1f} mi")

        if g.vehicle_id is None:
            if driver.needs_vehicle:
                errs.append(f"{tag}: driver trip {driver.id} needs a vehicle but vehicle_id is null")
            elif group_size(members) > C.OWN_CAR_SEATS:
                errs.append(f"{tag}: group has {group_size(members)} people, over {C.OWN_CAR_SEATS} seats for a driver's own car")
        elif g.vehicle_id not in ctx.vehicles:
            errs.append(f"{tag}: vehicle {g.vehicle_id} does not exist")
        else:
            v = ctx.vehicles[g.vehicle_id]
            errs += [f"{tag}: {e}" for e in vehicle_problems(ctx, driver, ordered, g.depart_time, v, taken)]
            start, end = booking_window(g.depart_time, rental_hours(shared_miles(ctx, driver, ordered, v)["shared_mi"]))
            taken.append(Booking(vehicle_id=v.id, start_ts=start, end_ts=end))

    for u in plan.unassigned:
        if u.trip_id in where:
            errs.append(f"trip {u.trip_id} is both in {where[u.trip_id]} and unassigned")
        elif u.trip_id not in ctx.trips:
            errs.append(f"unassigned trip {u.trip_id} does not exist or is not open for planning")
    return errs


# ---------------------------------------------------------------- deterministic fallback planner

def _window_overlap(members: list[Trip]) -> tuple[datetime, datetime]:
    return max(t.window_start for t in members), min(t.window_end for t in members)


def fallback_plan(ctx: Ctx) -> Plan:
    """Small and predictable: anchor on each driver trip, add nearby compatible passengers
    (nearest first) while seats, windows and detours allow. Vehicle and pickup order are
    left for complete(), so both planners share the CO2 vehicle rule."""
    trips = sorted((t for t in ctx.trips.values() if t.status != "cancelled"), key=lambda t: t.id)
    pool = [t for t in trips if t.role == "passenger"]
    active = [v.seats for v in ctx.vehicles.values() if v.active]
    plan = Plan()
    for d in (t for t in trips if t.role == "driver"):
        cap = (max(active) if active else 0) if d.needs_vehicle else C.OWN_CAR_SEATS
        near = sorted(
            (p for p in pool
             if ctx.dist(p.dest, d.dest) <= C.DEST_RADIUS_MI
             and ctx.dist(d.origin, p.origin) <= C.MAX_PICKUP_RADIUS_MI),
            key=lambda p: (ctx.dist(d.origin, p.origin), p.id))
        group: list[Trip] = []
        for p in near:
            trial = group + [p]
            ws, we = _window_overlap([d, *trial])
            if group_size([d, *trial]) > cap or we - ws < timedelta(minutes=C.MIN_WINDOW_OVERLAP_MIN):
                continue
            order = nearest_neighbor_order(ctx, d, trial)
            ordered = [ctx.trips[i] for i in order]
            if all(x <= detour_limit(ctx, ctx.trips[i]) + 1e-6 for i, x in added_detours(ctx, d, ordered).items()):
                group = trial
        if not group:
            plan.unassigned.append(Unassigned(trip_id=d.id, reason="no compatible passengers in window yet"))
            continue
        pool = [p for p in pool if p not in group]
        plan.groups.append(Group(
            driver_trip_id=d.id,
            passenger_trip_ids=[p.id for p in group],
            depart_time=_window_overlap([d, *group])[0],
            rationale=["same destination and overlapping time windows",
                       "pickups are close to the driver's starting point"],
        ))
    plan.unassigned += [Unassigned(trip_id=p.id, reason="no compatible driver in window") for p in pool]
    return plan


# ---------------------------------------------------------------- scoring and explanation

def member_scores(ctx: Ctx, driver: Trip, ordered: list[Trip]) -> dict[int, float]:
    """1.0 = no detour, 0.0 = at the passenger's detour limit."""
    scores = {driver.id: 1.0}
    for pid, extra in added_detours(ctx, driver, ordered).items():
        limit = max(detour_limit(ctx, ctx.trips[pid]), 0.1)
        scores[pid] = round(max(0.0, min(1.0, 1 - extra / limit)), 2)
    return scores


def template_explanation(f: dict) -> str:
    """f: driver, passengers [names], vehicle (label or None), kg_co2_shared, alt_vehicle, alt_kg_co2,
    cost_per_person_cents, miles_avoided, kg_co2_avoided, percent_reduction."""
    riders = " and ".join(f["passengers"]) if f["passengers"] else "no one yet"
    car = f"in the {f['vehicle']}" if f.get("vehicle") else "in their own car"
    s = [f"{f['driver']} drives {riders} {car}, with everyone going to the same place in overlapping time windows."]
    if f.get("alt_vehicle") and f.get("alt_kg_co2") is not None:
        s.append(f"This vehicle emits about {f['kg_co2_shared']:.1f} kg CO2 for the trip, versus "
                 f"{f['alt_kg_co2']:.1f} kg for the {f['alt_vehicle']}.")
    s.append(f"Sharing avoids {f['miles_avoided']:.1f} miles and {f['kg_co2_avoided']:.1f} kg CO2 "
             f"({f['percent_reduction']:.0f}% less than everyone driving separately), "
             f"at ${f['cost_per_person_cents'] / 100:.2f} per person.")
    return " ".join(s)
