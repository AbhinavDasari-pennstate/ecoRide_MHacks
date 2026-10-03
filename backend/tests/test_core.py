"""core.py unit tests: synthetic scenario Ctx, no DB, no network."""
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import config as C
from app import core
from app.core import Booking, Ctx, Group, Plan, Trip, Unassigned, Vehicle

DET = ZoneInfo("America/Detroit")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def local(h, m=0):
    return datetime(2026, 10, 10, h, m, tzinfo=DET).astimezone(timezone.utc)   # a Saturday


W0, W1 = local(13, 45), local(14, 30)
MEIJER = (42.2405, -83.7660)


def trip(id, user_id, role, lat, lng, **kw):
    return Trip(id=id, user_id=user_id, role=role, origin_lat=lat, origin_lng=lng, dest_name="Meijer",
                dest_lat=MEIJER[0], dest_lng=MEIJER[1], window_start=W0, window_end=W1, **kw)


def vehicle(id, make_model, fuel, eff, price, lat, lng, start=local(8), end=local(22), range_mi=300):
    return Vehicle(id=id, make_model=make_model, fuel_type=fuel, seats=5, range_mi=range_mi, efficiency=eff,
                   price_per_hour_cents=price, lat=lat, lng=lng, avail_start=start, avail_end=end)


TRIPS = [
    trip(1, 2, "passenger", 42.2800, -83.7330),                      # Maya
    trip(2, 3, "passenger", 42.2720, -83.7500),                      # Jordan
    trip(3, 1, "driver", 42.2780, -83.7400, needs_vehicle=True),     # Alex
]
VEHICLES = [
    vehicle(1, "Tesla Model 3", "ev", 0.25, 800, 42.2820, -83.7260, local(13), local(17), range_mi=272),
    vehicle(2, "Honda Civic", "gas", 36, 700, 42.2740, -83.7330, range_mi=400),
    vehicle(3, "Toyota RAV4", "gas", 30, 1000, 42.2620, -83.7180, range_mi=400),
    vehicle(4, "Nissan Leaf", "ev", 0.30, 900, 42.2650, -83.7500, local(13, 30), local(17), range_mi=149),
]


def scenario(dist=core.estimate_dist):
    return Ctx(trips={t.id: t for t in TRIPS}, vehicles={v.id: v for v in VEHICLES}, dist=dist)


def upd(d, id, **kw):
    d[id] = d[id].model_copy(update=kw)


def G(driver=3, passengers=(1, 2), vehicle=1, order=None, depart=W0):
    return Group(driver_trip_id=driver, passenger_trip_ids=list(passengers), vehicle_id=vehicle,
                 pickup_order=list(passengers if order is None else order), depart_time=depart)


def check(ctx, *groups, unassigned=()):
    return core.validate(Plan(groups=list(groups), unassigned=list(unassigned)), ctx)


def has(errs, *subs):
    assert any(all(s in e for s in subs) for e in errs), errs


def fake_dist(a, b):
    # every hop 1 mi, anything touching Meijer 4 mi: easy to add up by hand
    return 0.0 if a == b else 4.0 if MEIJER in (a, b) else 1.0


# ---------------------------------------------------------------- validate

def test_baseline_plan_is_valid():
    assert check(scenario(), G()) == []


def test_too_many_people_for_seats():
    ctx = scenario()
    upd(ctx.vehicles, 1, seats=2)
    has(check(ctx, G()), "vehicle 1", "2 seats", "3 people")
    ctx = scenario()
    upd(ctx.trips, 3, needs_vehicle=False)
    upd(ctx.trips, 1, party_size=3)
    has(check(ctx, G(vehicle=None)), "driver trip 3", "own car")


def test_ev_beyond_usable_range():
    ctx = scenario()
    upd(ctx.vehicles, 4, range_mi=10)
    has(check(ctx, G(vehicle=4)), "vehicle 4", "usable range")


def test_vehicle_outside_avail_window():
    ctx = scenario()
    upd(ctx.vehicles, 1, avail_start=W0 + timedelta(hours=1))
    has(check(ctx, G()), "vehicle 1", "is available")


def test_vehicle_already_booked():
    ctx = scenario()
    ctx.bookings = [Booking(id=7, match_id=9, vehicle_id=1, start_ts=W0 + timedelta(minutes=30), end_ts=W0 + timedelta(hours=3))]
    has(check(ctx, G()), "vehicle 1", "already booked", "booking 7")
    ctx.bookings[0].status = "declined"       # inactive bookings don't block
    assert check(ctx, G()) == []


def test_same_vehicle_twice_in_one_plan():
    ctx = scenario()
    ctx.trips[4] = trip(4, 6, "driver", 42.2620, -83.7180, needs_vehicle=True)
    has(check(ctx, G(), G(driver=4, passengers=())), "driver trip 4", "vehicle 1", "another group in this plan")


def test_trip_in_two_groups_or_also_unassigned():
    ctx = scenario()
    ctx.trips[4] = trip(4, 6, "driver", 42.2620, -83.7180, needs_vehicle=True)
    has(check(ctx, G(), G(driver=4, passengers=(2,), vehicle=4)), "trip 2 appears in more than one group")
    has(check(ctx, G(), unassigned=[Unassigned(trip_id=1, reason="x")]), "trip 1 is both in")


def test_window_mismatch():
    errs = check(scenario(), G(depart=W0 - timedelta(hours=4)))
    for i in (1, 2, 3):
        has(errs, f"outside trip {i}'s window")
    ctx = scenario()
    upd(ctx.trips, 2, window_start=local(15), window_end=local(16))
    errs = check(ctx, G())
    has(errs, "outside trip 2's window")
    assert not any("trip 1's window" in e for e in errs)


def test_bad_pickup_order():
    has(check(scenario(), G(order=[1])), "pickup_order [1]", "[1, 2]")
    has(check(scenario(), G(order=[1, 999])), "pickup_order [1, 999]")


def test_excess_detour():
    ctx = scenario()
    upd(ctx.trips, 1, max_detour_mi=0.5)
    has(check(ctx, G()), "picking up trip 1", "detour")
    has(check(scenario(), G(order=[2, 1])), "picking up trip 1", "detour")    # Jordan first makes Maya a long detour


def test_wrong_roles():
    errs = check(scenario(), G(driver=1, passengers=(3, 2)))
    has(errs, "trip 1 is a passenger trip and cannot be the driver")
    has(errs, "trip 3 is a driver trip and cannot ride as a passenger")


def test_cancelled_trip():
    ctx = scenario()
    upd(ctx.trips, 2, status="cancelled")
    has(check(ctx, G()), "trip 2 is cancelled")


def test_unknown_ids():
    has(check(scenario(), G(passengers=(1, 999))), "trip 999 does not exist")
    has(check(scenario(), G(driver=998)), "trip 998 does not exist")
    has(check(scenario(), G(vehicle=999)), "vehicle 999 does not exist")
    has(check(scenario(), G(), unassigned=[Unassigned(trip_id=997, reason="x")]), "unassigned trip 997")


def test_needs_vehicle_but_null():
    has(check(scenario(), G(vehicle=None)), "driver trip 3 needs a vehicle but vehicle_id is null")


def test_destination_too_far():
    ctx = scenario()
    upd(ctx.trips, 2, dest_lat=MEIJER[0] + 0.03)
    has(check(ctx, G()), "trip 2's destination")


def test_naive_depart_time_is_utc():
    g = Group(driver_trip_id=3, passenger_trip_ids=[1, 2], depart_time=W0.replace(tzinfo=None).isoformat())
    assert g.depart_time == W0
    assert check(scenario(), g.model_copy(update={"vehicle_id": 1, "pickup_order": [1, 2]})) == []


# ---------------------------------------------------------------- complete

def draft(**kw):
    return Plan(groups=[G(vehicle=None, order=[], **kw)])


def test_complete_picks_tesla_over_closer_cheaper_civic():
    ctx = scenario()
    plan, opts = core.complete(draft(), ctx)
    g = plan.groups[0]
    assert (g.vehicle_id, g.pickup_order) == (1, [1, 2])
    assert core.validate(plan, ctx) == []
    by_id = {o["vehicle_id"]: o for o in opts[3]}
    tesla, civic = by_id[1], by_id[2]
    assert civic["feasible"] and civic["deadhead_mi"] < tesla["deadhead_mi"] and civic["total_cost_cents"] < tesla["total_cost_cents"]
    assert tesla["kg_co2"] < civic["kg_co2"]
    assert opts[3][0]["vehicle_id"] == 1
    assert core.vehicle_reasons(opts[3], 1)[0].startswith("Tesla Model 3 (EV) chosen")


def test_complete_picks_leaf_when_tesla_inactive_or_booked():
    ctx = scenario()
    upd(ctx.vehicles, 1, active=False)
    assert core.complete(draft(), ctx)[0].groups[0].vehicle_id == 4
    ctx = scenario()
    ctx.bookings = [Booking(id=5, match_id=2, vehicle_id=1, start_ts=W0 - timedelta(minutes=30), end_ts=W0 + timedelta(hours=2))]
    plan, _ = core.complete(draft(), ctx)
    assert plan.groups[0].vehicle_id == 4
    assert core.validate(plan, ctx) == []


def test_complete_does_not_double_book_inside_plan():
    ctx = scenario()
    ctx.trips[4] = trip(4, 6, "driver", 42.2620, -83.7180, needs_vehicle=True)
    plan, _ = core.complete(Plan(groups=[G(vehicle=None, order=[]), G(driver=4, passengers=(), vehicle=None)]), ctx)
    assert [g.vehicle_id for g in plan.groups] == [1, 4]
    assert core.validate(plan, ctx) == []


def test_complete_unassigns_when_nothing_feasible():
    ctx = scenario()
    for v in list(ctx.vehicles):
        upd(ctx.vehicles, v, active=False)
    plan, opts = core.complete(draft(), ctx)
    assert plan.groups == []
    assert sorted(u.trip_id for u in plan.unassigned) == [1, 2, 3]
    assert all("no feasible vehicle" in u.reason for u in plan.unassigned)
    assert not any(o["feasible"] for o in opts[3])
    assert core.validate(plan, ctx) == []


def test_complete_keeps_bad_group_so_validate_reports_it():
    # a bad depart_time also makes every vehicle unavailable; that must not pass as "unassigned"
    plan, _ = core.complete(Plan(groups=[G(vehicle=None, order=[], depart=W0 - timedelta(hours=4))]), scenario())
    assert [g.driver_trip_id for g in plan.groups] == [3] and plan.unassigned == []
    has(core.validate(plan, scenario()), "outside trip 3's window")


def test_complete_keeps_provided_vehicle_and_order():
    plan, _ = core.complete(Plan(groups=[G(vehicle=2, order=[2, 1])]), scenario())
    assert (plan.groups[0].vehicle_id, plan.groups[0].pickup_order) == (2, [2, 1])


def test_co2_ties_go_to_cheaper(monkeypatch):
    monkeypatch.setattr(C, "GRID_KG_CO2_PER_KWH", 0.5)
    monkeypatch.setattr(C, "CO2_TIE_KG", 0.1)
    base = VEHICLES[1].model_copy(update={"fuel_type": "ev", "lat": 0.0, "lng": 0.0})

    def pick(*specs):   # (id, kWh/mi, $/hr cents); shared trip is 10 mi so kg = 5 * eff
        ctx = scenario(fake_dist)
        ctx.vehicles = {i: base.model_copy(update={"id": i, "make_model": f"EV{i}", "efficiency": e, "price_per_hour_cents": p})
                        for i, e, p in specs}
        return core.vehicle_options(ctx, ctx.trips[3], [], W0)[0]["vehicle_id"]

    assert pick((1, 0.028, 900), (2, 0.044, 800), (3, 0.06, 100)) == 2   # 0.14 vs 0.22 kg: tie, cheaper wins; 0.30 is not a tie
    assert pick((1, 0.028, 900), (2, 0.05, 800)) == 1                    # 0.14 vs 0.25 kg: lower CO2 wins


# ---------------------------------------------------------------- pricing, hours, impact

def test_pricing_rounding_invariants():
    rnd = random.Random(42)
    for _ in range(3000):
        v = rnd.choice(VEHICLES + [None])
        if v:
            v = v.model_copy(update={"price_per_hour_cents": rnd.randint(0, 5000)})
        size, miles = rnd.randint(1, 8), rnd.uniform(0, 300)
        p = core.pricing(v, miles, size)
        assert p["raw_cost_cents"] == p["rental_cents"] + p["energy_cents"]
        assert p["cost_per_person_cents"] == math.ceil(p["raw_cost_cents"] / size)
        assert p["cost_per_person_cents"] * size == p["total_cost_cents"]
        assert 0 <= p["rounding_cents"] <= size - 1
        assert all(isinstance(p[k], int) for k in ("rental_cents", "energy_cents", "raw_cost_cents", "total_cost_cents", "rounding_cents"))


def test_rental_hours_rounds_up_to_half_hour(monkeypatch):
    monkeypatch.setattr(C, "AVG_SPEED_MPH", 25)
    monkeypatch.setattr(C, "STOP_BUFFER_HOURS", 1.0)
    monkeypatch.setattr(C, "RENTAL_INCREMENT_HOURS", 0.5)
    assert [core.rental_hours(m) for m in (0, 1, 12.5, 12.6, 25, 25.1)] == [1.0, 1.5, 1.5, 2.0, 2.0, 2.5]
    rnd = random.Random(1)
    for _ in range(500):
        m = rnd.uniform(0, 200)
        h, raw = core.rental_hours(m), m / 25 + 1.0
        assert (h * 2).is_integer() and raw - 1e-6 <= h < raw + 0.5


def test_impact_hand_calculated(monkeypatch):
    for k, v in {"GRID_KG_CO2_PER_KWH": 0.5, "BASELINE_KG_CO2_PER_MILE": 0.4, "OWN_CAR_MPG": 25.0, "GAS_KG_CO2_PER_GALLON": 8.887}.items():
        monkeypatch.setattr(C, k, v)
    ctx = scenario(fake_dist)
    alex, maya, jordan = ctx.trips[3], ctx.trips[1], ctx.trips[2]
    # deadhead 2 * 1; route (1 + 1 + 4) * 2 = 12; shared 14. baseline 3 trips * 2 * 4 = 24.
    # kg: 14 * 0.25 kWh/mi * 0.5 = 1.75 vs 24 * 0.4 = 9.6 -> 7.85 avoided, 81.8%
    imp = core.impact(ctx, alex, [maya, jordan], ctx.vehicles[1])
    assert {k: imp[k] for k in imp if k != "assumptions"} == {
        "shared_miles": 14.0, "deadhead_miles": 2.0, "route_miles": 12.0, "baseline_miles": 24.0, "miles_avoided": 10.0,
        "kg_co2_shared": 1.75, "kg_co2_baseline": 9.6, "kg_co2_avoided": 7.85, "percent_reduction": 81.8,
    }
    # own car: no deadhead, 12 mi / 25 mpg * 8.887 = 4.27 kg
    own = core.impact(ctx, alex, [maya, jordan], None)
    assert (own["shared_miles"], own["deadhead_miles"], own["kg_co2_shared"], own["kg_co2_avoided"]) == (12.0, 0.0, 4.27, 5.33)


def test_assumptions_always_present():
    ctx = scenario()
    t = ctx.trips
    for src in ("estimate", "google_routes", "mixed"):
        a = core.impact(ctx, t[3], [t[1]], ctx.vehicles[2], distance_source=src)["assumptions"]
        assert a["distance_source"] == src and set(C.SOURCES) <= set(a)
    assert core.impact(ctx, t[3], [], None)["assumptions"]["distance_source"] == "estimate"


# ---------------------------------------------------------------- fallback planner

def test_fallback_plan_scenario_offline():
    assert not {"maps", "httpx", "psycopg", "genai", "db"} & set(vars(core))     # pure: nothing to reach the network
    ctx = scenario()
    plan = core.fallback_plan(ctx)
    assert [(g.driver_trip_id, sorted(g.passenger_trip_ids), g.depart_time) for g in plan.groups] == [(3, [1, 2], W0)]
    assert plan.unassigned == []
    done, _ = core.complete(plan, ctx)
    assert core.validate(done, ctx) == []
    assert (done.groups[0].vehicle_id, done.groups[0].pickup_order) == (1, [1, 2])
    assert not any(c.isdigit() for r in done.groups[0].rationale for c in r)


def test_fallback_leaves_lone_passenger_unassigned():
    ctx = scenario()
    ctx.trips = {1: ctx.trips[1]}
    plan = core.fallback_plan(ctx)
    assert plan.groups == [] and [u.trip_id for u in plan.unassigned] == [1] and plan.unassigned[0].reason

    ctx = scenario()
    ctx.trips[5] = trip(5, 7, "passenger", 42.2650, -83.7500).model_copy(update={"dest_lat": 42.2900, "dest_lng": -83.7150})
    plan, _ = core.complete(core.fallback_plan(ctx), ctx)
    assert [u.trip_id for u in plan.unassigned] == [5] and plan.unassigned[0].reason
    assert core.validate(plan, ctx) == []


def test_template_explanation_smoke():
    f = {"driver": "Alex", "passengers": ["Maya", "Jordan"], "vehicle": "Tesla Model 3 (EV)", "kg_co2_shared": 1.46,
         "alt_vehicle": "Honda Civic (gas)", "alt_kg_co2": 2.69, "cost_per_person_cents": 534, "miles_avoided": 10.2,
         "kg_co2_avoided": 3.9, "percent_reduction": 73.0}
    assert "Alex drives Maya and Jordan in the Tesla Model 3 (EV)" in core.template_explanation(f)
    assert "own car" in core.template_explanation({**f, "vehicle": None, "alt_vehicle": None, "alt_kg_co2": None, "passengers": []})


# ---------------------------------------------------------------- fixtures

def load_fixture(name):
    text = (FIXTURES / name).read_text()
    text = text.replace("{DEPART_BAD}", (W0 - timedelta(hours=4)).isoformat()).replace("{DEPART}", W0.isoformat())
    return json.loads(text)


def test_fixture_plans():
    ctx = scenario()
    plan, _ = core.complete(Plan.model_validate(load_fixture("plan_valid.json")), ctx)
    assert core.validate(plan, ctx) == []
    assert (plan.groups[0].driver_trip_id, plan.groups[0].vehicle_id) == (3, 1)

    cases = load_fixture("plans_invalid.json")
    assert len(cases) >= 6
    for case in cases:
        plan, _ = core.complete(Plan.model_validate(case["plan"]), ctx)
        errs = core.validate(plan, ctx)
        assert errs, case["name"]
        for sub in case["expect"]:
            assert any(sub in e for e in errs), (case["name"], sub, errs)
