"""Orchestration and state transitions. A planning run is: pick the trips in scope -> build a
Ctx (distances from Maps) -> planner draft (Gemini or fallback, completed and validated) ->
code computes route, price, impact -> one transaction writes matches, members, bookings, events.
Everything returned is JSON-ready (datetimes as ISO strings)."""
import math
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg

from app import config, core, db, maps, planner

_lock = threading.Lock()   # ponytail: single process; the advisory lock only guards the DB side

TRIP_FIELDS = ("user_id", "role", "origin_lat", "origin_lng", "dest_name", "dest_place_id", "dest_lat", "dest_lng",
               "window_start", "window_end", "party_size", "max_detour_mi", "needs_vehicle")
VEHICLE_FIELDS = ("owner_id", "make_model", "fuel_type", "seats", "range_mi", "efficiency", "price_per_hour_cents",
                  "lat", "lng", "avail_start", "avail_end", "efficiency_source")
# match columns written from _numbers()
COLS = ("vehicle_id", "depart_time", "pickup_order", "route", "raw_cost_cents", "total_cost_cents",
        "cost_per_person_cents", "pricing", "impact", "reasons", "explanation", "assumptions")


# ---------------------------------------------------------------- small helpers

def _out(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime)
            else float(v) if isinstance(v, Decimal) else v for k, v in row.items()}


def _ts(v) -> datetime:
    t = datetime.fromisoformat(v) if isinstance(v, str) else v
    if not isinstance(t, datetime):
        raise ValueError(f"not a datetime: {v!r}")
    if t.tzinfo is None:
        t = t.replace(tzinfo=ZoneInfo(config.TIMEZONE))   # ponytail: naive times are campus-local
    return t.astimezone(timezone.utc)


def _db(v):
    return db.J(v) if isinstance(v, (dict, list)) else v


def _one(c, sql, args=()):
    """fetchone; constraint and bad-value errors from Postgres become ValueError (422)."""
    try:
        return c.execute(sql, args).fetchone()
    except (psycopg.IntegrityError, psycopg.DataError) as e:
        raise ValueError(str(e).splitlines()[0]) from None


def _get(c, table, id_):
    row = c.execute(f"select * from {table} where id = %s", (id_,)).fetchone()
    if not row:
        raise LookupError(f"no {table} row with id {id_}")
    return row


def _trips(c, where, args=()) -> dict[int, core.Trip]:
    return {r["id"]: core.Trip(**r) for r in c.execute(f"select * from trips where {where} order by id", args)}


def _clean(data: dict, fields) -> dict:
    d = {k: v for k, v in data.items() if k in fields and v is not None}
    for k in ("window_start", "window_end", "avail_start", "avail_end"):
        if k in d:
            d[k] = _ts(d[k])
    return d


def _geocode_dest(d: dict) -> None:
    if "dest_name" in d and ("dest_lat" not in d or "dest_lng" not in d):
        g = maps.geocode(d["dest_name"])
        if not g:
            raise ValueError(f"could not find {d['dest_name']!r}; send dest_lat and dest_lng")
        d.update(dest_lat=g["lat"], dest_lng=g["lng"], dest_place_id=g.get("place_id"))


def _active_matches(c, trip_id) -> list[int]:
    return [r["match_id"] for r in c.execute(
        "select mm.match_id from match_members mm join matches m on m.id = mm.match_id"
        " where mm.trip_id = %s and mm.status <> 'cancelled' and m.status <> 'cancelled' order by mm.match_id",
        (trip_id,))]


# ---------------------------------------------------------------- planning run

def run_planning(trigger: str, trip_id: int | None = None, *, match_id: int | None = None, cause: str | None = None,
                 mode: str | None = None, dry_run: bool = False, plan: dict | None = None) -> dict:
    with _lock:
        with db.conn() as c:   # its own commit, so the activity feed shows "planning" while Gemini thinks
            db.event(c, "planning_started", {"trigger": trigger, "trip_id": trip_id, "match_id": match_id,
                                             "cause": cause, "dry_run": dry_run, "manual": plan is not None})
        try:
            with db.conn() as c:
                db.lock(c)
                return _run(c, trigger, trip_id, match_id, cause, mode, dry_run, plan)
        except Exception as e:
            with db.conn() as c:
                db.event(c, "planning_failed", {"trigger": trigger, "trip_id": trip_id, "match_id": match_id,
                                                "error": f"{type(e).__name__}: {e}"[:500]})
            raise


def _run(c, trigger, trip_id, match_id, cause, mode, dry_run, plan) -> dict:
    t0 = time.monotonic()
    manual =core.Plan.model_validate(plan) if plan is not None else None   # pydantic errors are ValueErrors
    trips = _scope(c, trip_id, match_id, manual)
    replanned = _replanned(c, trips, match_id)
    m = maps.Maps(c)
    ctx = _ctx(c, trips, list(replanned), m)

    if manual:
        draft, opts = core.complete(manual, ctx)
        errors = core.validate(draft, ctx)
        log = _log(trigger, t0, [manual.model_dump_json()], [errors])
    elif not trips:
        draft, opts, errors, log = core.Plan(), {}, [], _log(trigger, t0, [], [])
    else:
        replan = _replan_info(replanned[match_id], cause, trip_id) if match_id else None
        draft, opts, log = planner.draft(ctx, trigger, mode=mode, replan=replan)
        errors = core.validate(draft, ctx)   # nothing unvalidated reaches the DB, whoever drafted it

    run_id = db.agent_run(c, **log)
    for n, errs in enumerate(log["validator_errors"], 1):
        if errs:
            db.event(c, "plan_attempt_rejected", {"agent_run_id": run_id, "attempt": n, "errors": errs})
    if log["fallback_used"]:
        db.event(c, "fallback_used", {"agent_run_id": run_id})
    out = {"agent_run_id": run_id, "match_ids": [], "fallback_used": log["fallback_used"], "diffs": [],
           "unassigned": [u.model_dump() for u in draft.unassigned]}
    if errors and not manual:
        db.event(c, "planning_failed", {"agent_run_id": run_id, "errors": errors})
    if dry_run:
        db.event(c, "planning_finished", {"agent_run_id": run_id, "dry_run": True, "valid": not errors})
    if errors or dry_run:
        return out | {"plan": draft.model_dump(mode="json"), "valid": not errors, "errors": errors}

    db.event(c, "plan_validated", {"agent_run_id": run_id, "groups": len(draft.groups), "unassigned": len(draft.unassigned)})
    out |= _apply(c, ctx, m, draft, opts, replanned, cause or trigger, run_id)
    if manual:
        out |= {"valid": True, "errors": []}
    db.event(c, "planning_finished", {"agent_run_id": run_id, "match_ids": out["match_ids"],
                                      "unassigned": [u["trip_id"] for u in out["unassigned"]]})
    return out


def _log(trigger, t0, raw, errors) -> dict:
    """run_log for runs that skip the planner (manual plan, nothing in scope)."""
    return {"trigger": trigger, "planner": "deterministic", "tool_calls": [], "raw_output": raw,
            "validator_errors": errors, "retries": 0, "latency_ms": int((time.monotonic() - t0) * 1000),
            "fallback_used": False}


def _scope(c, trip_id, match_id, manual) -> dict[int, core.Trip]:
    if manual:
        ids = [i for g in manual.groups for i in (g.driver_trip_id, *g.passenger_trip_ids)]
        return _trips(c, "id = any(%s::int[])", (ids + [u.trip_id for u in manual.unassigned],))
    open_ = _trips(c, "status = 'open'")
    if match_id is not None:
        mt = _get(c, "matches", match_id)
        if mt["status"] == "cancelled":
            raise ValueError(f"match {match_id} is cancelled")
        scope = _trips(c, "status <> 'cancelled' and id in (select trip_id from match_members"
                          " where match_id = %s and status <> 'cancelled')", (match_id,))
        anchor = core.Trip(**_get(c, "trips", mt["driver_trip_id"]))
    elif trip_id is not None:
        scope, anchor = {}, core.Trip(**_get(c, "trips", trip_id))
    else:
        return open_
    # ponytail: one hop of "nearby" (same destination, overlapping window); late riders don't join existing matches
    return scope | {i: t for i, t in open_.items()
                    if core.haversine_mi(t.dest, anchor.dest) <= config.DEST_RADIUS_MI
                    and t.window_start < anchor.window_end and anchor.window_start < t.window_end}


def _replanned(c, trips, match_id) -> dict[int, dict]:
    """Matches being replanned: match_id plus any live match holding a trip in scope."""
    rows = c.execute(
        "select * from matches where status <> 'cancelled' and (id = %s or id in (select match_id from match_members"
        " where status <> 'cancelled' and trip_id = any(%s::int[]))) order by id", (match_id, list(trips)))
    return {r["id"]: r for r in rows}


def _ctx(c, trips, replanned_ids, m) -> core.Ctx:
    vehicles = {r["id"]: core.Vehicle(**r) for r in c.execute("select * from vehicles order by id")}
    # ponytail: a declined booking keeps blocking its vehicle for that slot (the owner said no), so replans can't re-pick it
    rows = c.execute("select * from bookings where status = 'declined' or (status in ('requested', 'approved')"
                     " and not match_id = any(%s::int[]))", (replanned_ids,))
    bookings = [core.Booking(**{**r, "status": "requested"}) for r in rows]
    pts = {p for t in trips.values() for p in (t.origin, t.dest)} | {v.loc for v in vehicles.values()}
    m.prefetch(sorted(pts))
    return core.Ctx(trips, vehicles, bookings, m.dist)


def _replan_info(mt, cause, trip_id) -> dict:
    info = {"cause": cause, "match_id": mt["id"],
            "previous_group": {"driver_trip_id": mt["driver_trip_id"], "passenger_trip_ids": mt["pickup_order"],
                               "vehicle_id": mt["vehicle_id"], "depart_time": _out(mt)["depart_time"]}}
    if cause == "vehicle_cancelled":
        info["cancelled_vehicle_id"] = mt["vehicle_id"]
    if cause == "trip_cancelled":
        info["cancelled_trip_id"] = trip_id
    return info


# ---------------------------------------------------------------- numbers (code owns all of them)

def _numbers(ctx, m, g, opts, names) -> dict:
    driver = ctx.trips[g.driver_trip_id]
    v = ctx.vehicles.get(g.vehicle_id)
    order = list(g.pickup_order)
    pts = [ctx.trips[i].origin for i in order]
    r = m.route(driver.origin, pts, driver.dest)
    maps_order = [order[i] for i in r["order"]]
    if maps_order != order:
        if core.validate(core.Plan(groups=[g.model_copy(update={"pickup_order": maps_order})]), ctx):
            r = m.route(driver.origin, pts, driver.dest, optimize=False)   # Maps' order breaks a rule: keep ours
        else:
            order = maps_order
    ordered = [ctx.trips[i] for i in order]
    price = core.pricing(v, core.shared_miles(ctx, driver, ordered, v)["shared_mi"], core.group_size([driver, *ordered]))
    imp = core.impact(ctx, driver, ordered, v, distance_source=m.source)
    assumptions = imp.pop("assumptions")
    if v:
        assumptions["vehicle_efficiency"] = {"value": v.efficiency,
            "unit": "kWh/mi" if v.fuel_type == "ev" else "mpg", "source": v.efficiency_source}
    alt = next((o for o in opts if o["feasible"] and o["fuel_type"] == "gas" and o["vehicle_id"] != g.vehicle_id), None)
    facts = {"driver": names[driver.id], "passengers": [names[t.id] for t in ordered], "vehicle": v.label if v else None,
             "kg_co2_shared": imp["kg_co2_shared"], "alt_vehicle": ctx.vehicles[alt["vehicle_id"]].label if alt else None,
             "alt_kg_co2": alt["kg_co2"] if alt else None, "cost_per_person_cents": price["cost_per_person_cents"],
             "miles_avoided": imp["miles_avoided"], "kg_co2_avoided": imp["kg_co2_avoided"],
             "percent_reduction": imp["percent_reduction"]}
    route_stops = [{"kind": "vehicle", "vehicle_id": v.id, "name": v.make_model, "lat": v.lat, "lng": v.lng}] if v else []
    route_stops += [{"kind": "driver" if t is driver else "pickup", "trip_id": t.id, "name": names[t.id],
                     "lat": t.origin_lat, "lng": t.origin_lng} for t in [driver, *ordered]]
    route_stops.append({"kind": "destination", "name": driver.dest_name, "lat": driver.dest_lat, "lng": driver.dest_lng})
    booking = None
    if v:
        start, end = core.booking_window(g.depart_time, price["rental_hours"])
        booking = {"vehicle_id": v.id, "start_ts": start, "end_ts": end, "hours": price["rental_hours"],
                   "price_cents": price["rental_cents"]}
    return {
        "driver_trip_id": driver.id, "trip_ids": [driver.id, *order], "vehicle_id": g.vehicle_id,
        "depart_time": g.depart_time, "pickup_order": order,
        "route": {"polyline": r["polyline"], "distance_mi": r["distance_mi"], "duration_min": r["duration_min"],
                  "legs": r["legs"], "source": r["source"], "stops": route_stops},
        "raw_cost_cents": price["raw_cost_cents"], "total_cost_cents": price["total_cost_cents"],
        "cost_per_person_cents": price["cost_per_person_cents"], "pricing": price, "impact": imp,
        "reasons": {"grouping": g.rationale, "vehicle": core.vehicle_reasons(opts, g.vehicle_id), "vehicle_options": opts},
        "explanation": planner.explain(facts), "assumptions": assumptions,
        "scores": core.member_scores(ctx, driver, ordered), "booking": booking,
    }


# ---------------------------------------------------------------- apply (inside the run's transaction)

def _apply(c, ctx, m, plan, opts, replanned, cause, run_id) -> dict:
    names = {r["id"]: r["name"] for r in c.execute(
        "select t.id, u.name from trips t join users u on u.id = t.user_id where t.id = any(%s::int[])", (list(ctx.trips),))}
    by_driver = {r["driver_trip_id"]: r for r in replanned.values()}
    placed, match_ids, diffs = {}, [], []
    for g in plan.groups:
        n = _numbers(ctx, m, g, opts.get(g.driver_trip_id, []), names)
        old = by_driver.get(g.driver_trip_id)
        if old:
            diffs.append(_update_match(c, old, n, cause, run_id))
            mid = old["id"]
        else:
            mid = _create_match(c, n, run_id)
        match_ids.append(mid)
        placed |= {i: mid for i in n["trip_ids"]}
    for i, mid in placed.items():   # a trip lives in one match: drop it from the one it left
        c.execute("update match_members set status = 'cancelled' where trip_id = %s and match_id <> %s"
                  " and status <> 'cancelled'", (i, mid))
    for old in replanned.values():
        if old["id"] in match_ids:
            continue
        driver_status = _get(c, "trips", old["driver_trip_id"])["status"]
        status = "cancelled" if driver_status == "cancelled" else "at_risk" if old["driver_trip_id"] in ctx.trips else None
        if status:
            diffs.append(_retire(c, old, status, cause, run_id))
            match_ids.append(old["id"])
    reasons = {u.trip_id: u.reason for u in plan.unassigned}
    left = [i for i, t in ctx.trips.items() if t.status != "cancelled" and i not in placed]
    c.execute("update trips set status = 'open' where id = any(%s::int[]) and status <> 'cancelled'", (left,))
    return {"match_ids": match_ids, "diffs": diffs,
            "unassigned": [{"trip_id": i, "reason": reasons.get(i, "not placed in any group")} for i in left]}


def _create_match(c, n, run_id) -> int:
    cols = ("driver_trip_id", *COLS)
    mid = c.execute(f"insert into matches ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) returning id",
                    [_db(n[k]) for k in cols]).fetchone()["id"]
    _members(c, mid, n)
    c.execute("update trips set status = 'matched' where id = any(%s::int[])", (n["trip_ids"],))
    db.event(c, "match_created", {"match_id": mid, "agent_run_id": run_id, "driver_trip_id": n["driver_trip_id"],
                                  "trip_ids": n["trip_ids"], "vehicle_id": n["vehicle_id"]})
    _book(c, mid, n, "requested", run_id)
    return mid


def _update_match(c, old, n, cause, run_id) -> dict:
    mid = old["id"]
    before = _snapshot(c, mid)
    prev = {r["trip_id"] for r in c.execute(
        "select trip_id from match_members where match_id = %s and status <> 'cancelled'", (mid,))}
    previous_booking = c.execute("select * from bookings where match_id = %s and status in ('requested', 'approved')",
                                 (mid,)).fetchone()
    b = n["booking"]
    # Approval carries forward only for exactly the reservation the owner approved.
    approved = bool(b and previous_booking and previous_booking["status"] == "approved"
                    and all(previous_booking[k] == b[k] for k in ("vehicle_id", "start_ts", "end_ts", "price_cents")))
    c.execute("update bookings set status = 'cancelled' where match_id = %s and status in ('requested', 'approved')", (mid,))
    status = "proposed"
    c.execute(f"update matches set {', '.join(f'{k} = %s' for k in COLS)}, status = %s, updated_at = now() where id = %s",
              [*(_db(n[k]) for k in COLS), status, mid])
    c.execute("update match_members set status = 'cancelled' where match_id = %s and not trip_id = any(%s::int[])",
              (mid, n["trip_ids"]))
    _members(c, mid, n)
    if any(old[k] != n[k] for k in ("vehicle_id", "depart_time", "cost_per_person_cents", "pickup_order")):
        c.execute("update match_members set status = 'pending' where match_id = %s and status <> 'cancelled'", (mid,))
        db.event(c, "member_reconfirmation_required", {"match_id": mid, "cause": cause})
    new = [i for i in n["trip_ids"] if i not in prev]
    c.execute("update trips set status = 'matched' where id = any(%s::int[]) and (status = 'open' or id = any(%s::int[]))",
              (n["trip_ids"], new))
    _book(c, mid, n, "approved" if approved else "requested", run_id)
    c.execute("update trips set status = 'matched' where id = any(%s::int[]) and status <> 'cancelled'", (n["trip_ids"],))
    return _changed(c, mid, cause, before, "match_updated", run_id)


def _retire(c, old, status, cause, run_id) -> dict:
    """Match whose driver is cancelled (-> cancelled) or has no feasible group (-> at_risk)."""
    mid = old["id"]
    before = _snapshot(c, mid)
    c.execute("update bookings set status = 'cancelled' where match_id = %s and status in ('requested', 'approved')", (mid,))
    if status == "cancelled":
        c.execute("update match_members set status = 'cancelled' where match_id = %s", (mid,))
    c.execute("update matches set status = %s, vehicle_id = null, updated_at = now() where id = %s", (status, mid))
    return _changed(c, mid, cause, before, "match_at_risk" if status == "at_risk" else "match_updated", run_id)


def _changed(c, mid, cause, before, kind, run_id) -> dict:
    after = _snapshot(c, mid)
    c.execute("update matches set last_change = %s where id = %s", (db.J({"cause": cause, "before": before, "after": after}), mid))
    diff = {"match_id": mid, "cause": cause, "before": before, "after": after}
    db.event(c, kind, {**diff, "agent_run_id": run_id})
    _maybe_confirm(c, mid)
    return diff


def _members(c, mid, n) -> None:
    for i in n["trip_ids"]:
        c.execute("insert into match_members (match_id, trip_id, match_score) values (%s, %s, %s)"
                  " on conflict (match_id, trip_id) do update set match_score = excluded.match_score,"
                  " status = case when match_members.status = 'cancelled' then 'pending' else match_members.status end",
                  (mid, i, n["scores"][i]))


def _book(c, mid, n, status, run_id) -> None:
    b = n["booking"]
    if not b:
        return
    bid = c.execute("insert into bookings (match_id, vehicle_id, start_ts, end_ts, hours, price_cents, status)"
                    " values (%s, %s, %s, %s, %s, %s, %s) returning id",
                    (mid, b["vehicle_id"], b["start_ts"], b["end_ts"], b["hours"], b["price_cents"], status)).fetchone()["id"]
    db.event(c, "booking_requested", {"booking_id": bid, "match_id": mid, "vehicle_id": b["vehicle_id"],
                                      "status": status, "agent_run_id": run_id})


def _snapshot(c, mid) -> dict:
    r = c.execute("select m.pickup_order, m.cost_per_person_cents, m.total_cost_cents, m.impact,"
                  " v.id as vid, v.make_model, v.fuel_type from matches m left join vehicles v on v.id = m.vehicle_id"
                  " where m.id = %s", (mid,)).fetchone()
    imp = r["impact"] or {}
    return {"vehicle": {"id": r["vid"], "make_model": r["make_model"], "fuel_type": r["fuel_type"]} if r["vid"] else None,
            "pickup_order": r["pickup_order"], "cost_per_person_cents": r["cost_per_person_cents"],
            "total_cost_cents": r["total_cost_cents"], "shared_miles": imp.get("shared_miles"),
            "kg_co2_shared": imp.get("kg_co2_shared"), "kg_co2_avoided": imp.get("kg_co2_avoided")}


def _maybe_confirm(c, mid) -> None:
    """proposed -> confirmed once every live member accepted and the booking is approved (or no vehicle)."""
    r = c.execute("select m.status, m.vehicle_id, count(*) filter (where mm.status = 'pending') as pending,"
                  " count(*) filter (where mm.status = 'accepted') as accepted,"
                  " exists (select 1 from bookings b where b.match_id = m.id and b.status = 'approved') as approved"
                  " from matches m join match_members mm on mm.match_id = m.id where m.id = %s group by m.id", (mid,)).fetchone()
    if not r or r["status"] != "proposed" or r["pending"] or not r["accepted"] or (r["vehicle_id"] and not r["approved"]):
        return
    c.execute("update matches set status = 'confirmed', updated_at = now() where id = %s", (mid,))
    c.execute("update trips set status = 'confirmed' where id in"
              " (select trip_id from match_members where match_id = %s and status = 'accepted')", (mid,))
    db.event(c, "match_confirmed", {"match_id": mid})


def _replan(match_id, cause, trip_id=None) -> dict:
    res = run_planning(cause, trip_id, match_id=match_id, cause=cause)
    with db.conn() as c:
        status = _get(c, "matches", match_id)["status"]
    return {"match_id": match_id, "status": status,
            "diff": next((d for d in res["diffs"] if d["match_id"] == match_id), None)}


# ---------------------------------------------------------------- trips

def create_trip(data: dict) -> dict:
    d = _clean(data, TRIP_FIELDS)
    d.setdefault("needs_vehicle", d.get("role") == "driver")
    _geocode_dest(d)
    with db.conn() as c:
        db.lock(c)
        u = c.execute("select * from users where id = %s", (d.get("user_id"),)).fetchone()
        if not u:
            raise ValueError(f"user {d.get('user_id')} does not exist")
        d.setdefault("origin_lat", u["home_lat"])
        d.setdefault("origin_lng", u["home_lng"])
        row = _one(c, f"insert into trips ({', '.join(d)}) values ({', '.join(['%s'] * len(d))}) returning *", list(d.values()))
        db.event(c, "trip_created", {"trip_id": row["id"], "user_id": row["user_id"], "role": row["role"]})
    return _out(row)


def update_trip(trip_id: int, data: dict) -> dict:
    d = _clean(data, [f for f in TRIP_FIELDS if f not in ("user_id", "role")])
    if not d:
        raise ValueError("nothing to update")
    _geocode_dest(d)
    with db.conn() as c:
        db.lock(c)
        if _get(c, "trips", trip_id)["status"] == "cancelled":
            raise ValueError(f"trip {trip_id} is cancelled")
        row = _one(c, f"update trips set {', '.join(f'{k} = %s' for k in d)} where id = %s returning *", [*d.values(), trip_id])
        mids = _active_matches(c, trip_id)
        _mark_at_risk(c, mids)
        db.event(c, "trip_updated", {"trip_id": trip_id, "fields": list(d), "match_ids": mids})
    planning = _replan(mids[0], "trip_updated", trip_id) if mids else run_planning("trip_updated", trip_id)
    return {"trip": _out(row), "planning": planning}


def cancel_trip(trip_id: int) -> dict:
    with db.conn() as c:
        db.lock(c)
        row = _get(c, "trips", trip_id)
        if row["status"] == "cancelled":
            return {"trip": _out(row), "replans": []}
        mids = _active_matches(c, trip_id)
        row = c.execute("update trips set status = 'cancelled' where id = %s returning *", (trip_id,)).fetchone()
        c.execute("update match_members set status = 'cancelled' where trip_id = %s", (trip_id,))
        _mark_at_risk(c, mids)
        db.event(c, "trip_cancelled", {"trip_id": trip_id, "match_ids": mids})
    return {"trip": _out(row), "replans": [_replan(mid, "trip_cancelled", trip_id) for mid in mids]}


def matches_for_trip(trip_id: int) -> list[dict]:
    with db.conn() as c:
        _get(c, "trips", trip_id)
        return [_match_view(c, mid) for mid in reversed(_active_matches(c, trip_id))]


# ---------------------------------------------------------------- matches and bookings

def get_match(match_id: int) -> dict | None:
    with db.conn() as c:
        return _match_view(c, match_id)


def _match_view(c, match_id) -> dict | None:
    m = c.execute("select * from matches where id = %s", (match_id,)).fetchone()
    if not m:
        return None
    members = c.execute("select mm.trip_id, t.user_id, u.name, t.role, mm.status, mm.match_score"
                        " from match_members mm join trips t on t.id = mm.trip_id join users u on u.id = t.user_id"
                        " where mm.match_id = %s order by t.role = 'driver' desc, mm.trip_id", (match_id,)).fetchall()
    vehicle = c.execute("select * from vehicles where id = %s", (m["vehicle_id"],)).fetchone()
    booking = c.execute("select * from bookings where match_id = %s"
                        " order by status in ('requested', 'approved') desc, id desc limit 1", (match_id,)).fetchone()
    return {**_out(m), "members": members, "vehicle": _out(vehicle), "booking": _out(booking),
            "costs": {k: m[k] for k in ("raw_cost_cents", "total_cost_cents", "cost_per_person_cents")}}


def accept(match_id: int, user_id: int) -> dict:
    with db.conn() as c:
        db.lock(c)
        if _get(c, "matches", match_id)["status"] == "cancelled":
            raise ValueError(f"match {match_id} is cancelled")
        mm = c.execute("select mm.trip_id, mm.status from match_members mm join trips t on t.id = mm.trip_id"
                       " where mm.match_id = %s and t.user_id = %s and mm.status <> 'cancelled'", (match_id, user_id)).fetchone()
        if not mm:
            raise ValueError(f"user {user_id} is not a member of match {match_id}")
        if mm["status"] == "pending":
            c.execute("update match_members set status = 'accepted' where match_id = %s and trip_id = %s",
                      (match_id, mm["trip_id"]))
            db.event(c, "member_accepted", {"match_id": match_id, "trip_id": mm["trip_id"], "user_id": user_id})
        _maybe_confirm(c, match_id)
    return get_match(match_id)


def approve_booking(booking_id: int) -> dict:
    with db.conn() as c:
        db.lock(c)
        b = _get(c, "bookings", booking_id)
        if b["status"] not in ("requested", "approved"):
            raise ValueError(f"booking {booking_id} is {b['status']}")
        if b["status"] == "requested":
            b = c.execute("update bookings set status = 'approved' where id = %s returning *", (booking_id,)).fetchone()
            db.event(c, "booking_approved", {"booking_id": booking_id, "match_id": b["match_id"]})
        _maybe_confirm(c, b["match_id"])
    return {"booking": _out(b), "match": get_match(b["match_id"])}


def decline_booking(booking_id: int) -> dict:
    with db.conn() as c:
        db.lock(c)
        b = _get(c, "bookings", booking_id)
        live = b["status"] in ("requested", "approved")
        if live:
            b = c.execute("update bookings set status = 'declined' where id = %s returning *", (booking_id,)).fetchone()
            db.event(c, "booking_declined", {"booking_id": booking_id, "match_id": b["match_id"]})
            live = _get(c, "matches", b["match_id"])["status"] != "cancelled"
            if live:
                _mark_at_risk(c, [b["match_id"]])
    return {"booking": _out(b), "replan": _replan(b["match_id"], "booking_declined") if live else None}


# ---------------------------------------------------------------- vehicles

def create_vehicle(data: dict) -> dict:
    d = _clean(data, VEHICLE_FIELDS)
    with db.conn() as c:
        db.lock(c)
        if d.get("owner_id") is not None and ("lat" not in d or "lng" not in d):
            u = _one(c, "select * from users where id = %s", (d["owner_id"],))
            if not u:
                raise ValueError(f"user {d['owner_id']} does not exist")
            d.setdefault("lat", u["home_lat"])
            d.setdefault("lng", u["home_lng"])
        row = _one(c, f"insert into vehicles ({', '.join(d)}) values ({', '.join(['%s'] * len(d))}) returning *", list(d.values()))
        db.event(c, "vehicle_created", {"vehicle_id": row["id"], "owner_id": row["owner_id"]})
        at_risk = [r["id"] for r in c.execute("select id from matches where status = 'at_risk' order by id")]
    # ponytail: a new car retries every at_risk match; fine at campus scale
    return _out(row) | {"replans": [_replan(mid, "vehicle_added") for mid in at_risk]}


def cancel_vehicle(vehicle_id: int) -> dict:
    with db.conn() as c:
        db.lock(c)
        if not _get(c, "vehicles", vehicle_id)["active"]:
            return {"vehicle_id": vehicle_id, "replans": []}
        c.execute("update vehicles set active = false where id = %s", (vehicle_id,))
        mids = [r["match_id"] for r in c.execute(
            "update bookings b set status = 'cancelled' from matches m where m.id = b.match_id and b.vehicle_id = %s"
            " and b.status in ('requested', 'approved') and m.status <> 'cancelled' returning b.match_id", (vehicle_id,))]
        mids = sorted(set(mids))
        _mark_at_risk(c, mids)
        db.event(c, "vehicle_cancelled", {"vehicle_id": vehicle_id, "match_ids": mids})
    return {"vehicle_id": vehicle_id, "replans": [_replan(mid, "vehicle_cancelled") for mid in mids]}


def _mark_at_risk(c, mids):
    """Persist disruption before external planning; a failed replan must not leave a confirmed match."""
    c.execute("update matches set status = 'at_risk', updated_at = now() where id = any(%s::int[])"
              " and status <> 'cancelled'", (mids,))
    c.execute("update trips set status = 'matched' where status = 'confirmed' and id in"
              " (select trip_id from match_members where match_id = any(%s::int[]) and status <> 'cancelled')", (mids,))


# ---------------------------------------------------------------- shared account and dashboard data

def create_user(data: dict) -> dict:
    """Idempotent account creation using an identity verified by a trusted adapter."""
    with db.conn() as c:
        db.lock(c)
        identity = c.execute("select user_id from user_identities where provider = %s and subject = %s",
                             (data["provider"], data["subject"])).fetchone()
        if identity:
            return _out(_get(c, "users", identity["user_id"]))
        fields = ("name", "phone", "roles", "home_lat", "home_lng")
        row = _one(c, f"insert into users ({', '.join(fields)}) values (%s, %s, %s, %s, %s) returning *",
                   [data.get(k) for k in fields])
        c.execute("insert into user_identities(provider, subject, user_id) values (%s, %s, %s)",
                  (data["provider"], data["subject"], row["id"]))
        db.event(c, "user_created", {"user_id": row["id"]})
        return _out(row)


def link_identity(user_id: int, provider: str, subject: str) -> dict:
    with db.conn() as c:
        db.lock(c)
        _get(c, "users", user_id)
        row = c.execute("select user_id from user_identities where provider = %s and subject = %s",
                        (provider, subject)).fetchone()
        if row and row["user_id"] != user_id:
            raise ValueError("Identity is already linked to another account")
        if not row:
            c.execute("insert into user_identities(provider, subject, user_id) values (%s, %s, %s)",
                      (provider, subject, user_id))
            db.event(c, "identity_linked", {"user_id": user_id, "provider": provider})
        return {"user_id": user_id, "provider": provider, "subject": subject}


def dashboard(user_id: int) -> dict:
    with db.conn() as c:
        # Consistent view if an approval or replan commits during these reads.
        c.execute("set transaction isolation level repeatable read read only")
        user = _out(_get(c, "users", user_id))
        trips = [_out(r) for r in c.execute("select * from trips where user_id = %s order by created_at desc, id desc", (user_id,))]
        vehicles = [_out(r) for r in c.execute("select * from vehicles where owner_id = %s order by id", (user_id,))]
        mids = c.execute("select distinct m.id from matches m left join match_members mm on mm.match_id = m.id"
                         " left join trips t on t.id = mm.trip_id left join vehicles v on v.id = m.vehicle_id"
                         " where (t.user_id = %s and mm.status <> 'cancelled') or v.owner_id = %s order by m.id desc",
                         (user_id, user_id)).fetchall()
        return {"user": user, "trips": trips, "vehicles": vehicles,
                "matches": [_match_view(c, r["id"]) for r in mids]}


def list_vehicles(owner_id=None, active=True, limit=100, offset=0):
    with db.conn() as c:
        return [_out(r) for r in c.execute("select * from vehicles where (%s::int is null or owner_id = %s)"
                    " and (%s::boolean is null or active = %s) order by id limit %s offset %s",
                    (owner_id, owner_id, active, active, limit, offset))]


# ---------------------------------------------------------------- read models

def impact_summary() -> dict:
    with db.conn() as c:
        r = c.execute("select count(*) as matches, coalesce(sum((m.impact->>'miles_avoided')::float), 0) as miles,"
                      " coalesce(sum((m.impact->>'kg_co2_avoided')::float), 0) as kg,"
                      " coalesce(avg(coalesce(v.fuel_type = 'ev', false)::int), 0) as ev from matches m"
                      " left join vehicles v on v.id = m.vehicle_id where m.status in ('proposed', 'confirmed')").fetchone()
        trips = c.execute("select count(*) as n from match_members mm join matches m on m.id = mm.match_id"
                          " where m.status in ('proposed', 'confirmed') and mm.status <> 'cancelled'").fetchone()["n"]
    return {"matches": r["matches"], "trips": trips, "miles_avoided": round(r["miles"], 2),
            "kg_co2_avoided": round(r["kg"], 2), "ev_share": round(float(r["ev"]), 2), "simulated": False,
            "basis": "Projected savings for proposed and confirmed matches; not measured completed journeys"}


def events(since_id: int = 0, limit: int = 200) -> dict:
    with db.conn() as c:
        rows = c.execute("select * from events where id > %s order by id limit %s", (since_id, limit)).fetchall()
    return {"events": [_out(r) for r in rows], "last_id": rows[-1]["id"] if rows else since_id}


def agent_runs(limit: int = 50) -> list[dict]:
    with db.conn() as c:
        return [_out(r) for r in c.execute("select * from agent_runs order by id desc limit %s", (limit,))]


# The guided web demo uses real rows, isolated by explicit demo identities.
# Provisioning is additive; restarting cancels demo trips and retains their history.
def demo_bootstrap() -> dict:
    from scripts import seed
    avail_start, avail_end = seed.availability()
    users, vehicles = [], []
    with db.conn() as c:
        db.lock(c)
        for name, roles, lat, lng, _ in seed.USERS:
            alias = name.lower()
            row = c.execute("select u.* from users u join user_identities i on i.user_id = u.id"
                            " where i.provider = 'eride-demo' and i.subject = %s", (alias,)).fetchone()
            if not row:
                row = c.execute("insert into users(name, roles, home_lat, home_lng) values (%s,%s,%s,%s) returning *",
                                (name, roles, lat, lng)).fetchone()
                c.execute("insert into user_identities(provider, subject, user_id) values ('eride-demo',%s,%s)",
                          (alias, row["id"]))
            users.append({**_out(row), "alias": alias})
        for owner, model, fuel, eff, rng, cents in seed.VEHICLES:
            u = users[owner - 1]
            row = c.execute("select * from vehicles where owner_id = %s and make_model = %s order by id limit 1",
                            (u["id"], model)).fetchone()
            if not row:
                row = c.execute("insert into vehicles(owner_id, make_model, fuel_type, seats, range_mi, efficiency,"
                                "price_per_hour_cents, lat, lng, avail_start, avail_end, efficiency_source)"
                                " values (%s,%s,%s,5,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                                (u["id"], model, fuel, rng, eff, cents, u["home_lat"], u["home_lng"],
                                 avail_start, avail_end, seed.VEHICLE_SOURCES[model])).fetchone()
            vehicles.append(_out(row))
    start, end = seed.scenario_window()
    return {"users": users, "vehicles": vehicles, "destination": seed.MEIJER,
            "window_start": start.isoformat(), "window_end": end.isoformat()}


def demo_start() -> dict:
    meta = demo_bootstrap()
    by_alias = {u["alias"]: u for u in meta["users"]}
    with db.conn() as c:
        db.lock(c)
        driver = c.execute("select * from trips where user_id = %s and status <> 'cancelled' order by id desc limit 1",
                           (by_alias["alex"]["id"],)).fetchone()
        if not driver:
            for alias in ("maya", "jordan", "alex"):
                u = by_alias[alias]
                d = {"user_id": u["id"], "role": "driver" if alias == "alex" else "passenger",
                     "origin_lat": u["home_lat"], "origin_lng": u["home_lng"], **meta["destination"],
                     "window_start": _ts(meta["window_start"]), "window_end": _ts(meta["window_end"]),
                     "needs_vehicle": alias == "alex"}
                row = c.execute(f"insert into trips ({', '.join(d)}) values ({', '.join(['%s'] * len(d))}) returning *",
                                list(d.values())).fetchone()
                db.event(c, "trip_created", {"trip_id": row["id"], "user_id": u["id"], "role": d["role"]})
                if alias == "alex":
                    driver = row
        mids = _active_matches(c, driver["id"])
    if not mids or driver["status"] == "open":
        run_planning("web_demo", driver["id"])
    return {"trip": _out(driver)}


def demo_restart() -> dict:
    from scripts import seed
    meta = demo_bootstrap()
    ids = [u["id"] for u in meta["users"]]
    with db.conn() as c:
        db.lock(c)
        tids = [r["id"] for r in c.execute("select id from trips where user_id = any(%s::int[]) and status <> 'cancelled'", (ids,))]
        mids = [r["match_id"] for r in c.execute("select distinct match_id from match_members where trip_id = any(%s::int[])"
                                                " and status <> 'cancelled'", (tids,))]
        # A demo trip may have matched another account. Release its membership,
        # but never cancel that account's request or delete its data.
        c.execute("update trips set status = 'open' where status <> 'cancelled' and id in"
                  " (select trip_id from match_members where match_id = any(%s::int[]))", (mids,))
        c.execute("update bookings set status = 'cancelled' where match_id = any(%s::int[]) and status in ('requested','approved')", (mids,))
        c.execute("update match_members set status = 'cancelled' where match_id = any(%s::int[])", (mids,))
        c.execute("update matches set status = 'cancelled', updated_at = now() where id = any(%s::int[])", (mids,))
        c.execute("update trips set status = 'cancelled' where id = any(%s::int[])", (tids,))
        avail_start, avail_end = seed.availability()
        c.execute("update vehicles set active = true, avail_start = %s, avail_end = %s where id = any(%s::int[])",
                  (avail_start, avail_end, [v["id"] for v in meta["vehicles"]]))
        db.event(c, "demo_restarted", {"trip_ids": tids, "match_ids": mids})
    return {"ok": True}


def select_vehicle(match_id: int, vehicle_id: int) -> dict:
    m = get_match(match_id)
    if not m:
        raise LookupError("Match not found")
    plan = {"groups": [{"driver_trip_id": m["driver_trip_id"],
            "passenger_trip_ids": [p["trip_id"] for p in m["members"] if p["role"] == "passenger" and p["status"] != "cancelled"],
            "pickup_order": m["pickup_order"], "vehicle_id": vehicle_id, "depart_time": m["depart_time"],
            "rationale": ["Vehicle selected by the traveler"]}]}
    result = run_planning("vehicle_selected", match_id=match_id, plan=plan)
    if not result.get("valid", True):
        raise ValueError("; ".join(result["errors"]))
    return get_match(match_id)


# ---------------------------------------------------------------- buyer dataset

BUYER_VEHICLE = "Tesla Model 3"   # the dataset simulates one shared car
EVENT_LABELS = {"hard_brake": "Hard braking", "rapid_acceleration": "Rapid acceleration", "sharp_turn": "Sharp turn"}


def _r2(x: float) -> float:
    """JS Math.round(x * 100) / 100, so summaries match the frontend's original numbers."""
    return math.floor(x * 100 + 0.5) / 100


def _iso_ms(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def buyer_dataset() -> dict:
    """buyer_trips / buyer_events in the shape of the frontend's BuyerDataset; summaries derived here."""
    with db.conn() as c:
        trip_rows = c.execute("select * from buyer_trips order by started_at desc").fetchall()
        event_rows = c.execute("select * from buyer_events order by trip_id, offset_seconds").fetchall()
    events_by_trip: dict[str, list] = {}
    for e in event_rows:
        events_by_trip.setdefault(e["trip_id"], []).append({
            "id": e["id"], "tripId": e["trip_id"], "driverId": e["driver_id"], "type": e["type"],
            "timestamp": _iso_ms(e["at"]), "offsetSeconds": e["offset_seconds"], "severity": e["severity"],
            "detail": e["detail"], "value": e["value"], "unit": e["unit"], "threshold": e["threshold"]})
    trips = [{"id": t["id"], "driverId": t["driver_id"], "startedAt": _iso_ms(t["started_at"]), "miles": t["miles"],
              "durationMinutes": t["duration_minutes"], "estimatedEnergyKwh": t["estimated_energy_kwh"],
              "events": events_by_trip.get(t["id"], [])} for t in trip_rows]
    events = sorted((e for t in trips for e in t["events"]), key=lambda e: e["timestamp"], reverse=True)

    drivers = []
    for driver_id in sorted({t["driverId"] for t in trips}):
        mine = [t for t in trips if t["driverId"] == driver_id]
        miles = sum(t["miles"] for t in mine)
        evs = [e for t in mine for e in t["events"]]
        hard = sum(e["type"] == "hard_brake" for e in evs)
        drivers.append({"id": driver_id, "trips": len(mine), "miles": _r2(miles), "hardBrakes": hard,
                        "rapidAccelerations": sum(e["type"] == "rapid_acceleration" for e in evs),
                        "events": len(evs),
                        "hardBrakesPer100Miles": _r2(hard / miles * 100) if miles else 0,
                        "energyPer100Miles": _r2(sum(t["estimatedEnergyKwh"] for t in mine) / miles * 100) if miles else 0})

    dates = sorted({t["startedAt"][:10] for t in trips})
    summary = {"vehicle": BUYER_VEHICLE, "driverCount": len(drivers), "tripCount": len(trips),
               "dayCount": len(dates), "miles": _r2(sum(t["miles"] for t in trips)), "eventCount": len(events),
               "estimatedEnergyKwh": _r2(sum(t["estimatedEnergyKwh"] for t in trips)),
               "startDate": dates[0] if dates else None, "endDate": dates[-1] if dates else None}
    return {"datasetSummary": summary, "demoTrips": trips, "driverSummaries": drivers,
            "drivingEvents": events, "eventLabels": EVENT_LABELS}


# ---------------------------------------------------------------- live location

LOCATION_MAX_AGE_S = 15 * 60   # older positions are hidden rather than shown as current


def _location_role(c, match_id: int, user_id: int) -> dict:
    """The match status and this user's part in it: 'driver', 'passenger', 'owner' or None."""
    row = c.execute("select m.status, v.owner_id, (select t.role from match_members mm join trips t on t.id = mm.trip_id"
                    " where mm.match_id = m.id and t.user_id = %s and mm.status <> 'cancelled' limit 1) as role"
                    " from matches m left join vehicles v on v.id = m.vehicle_id where m.id = %s",
                    (user_id, match_id)).fetchone()
    if not row:
        raise LookupError("Match not found")
    return {"status": row["status"], "role": row["role"] or ("owner" if row["owner_id"] == user_id else None)}


def share_location(match_id: int, user_id: int, lat: float, lng: float, accuracy_m: float | None) -> dict:
    with db.conn() as c:
        who = _location_role(c, match_id, user_id)
        if who["status"] != "confirmed":
            raise ValueError("Location sharing starts once the ride is confirmed")
        if who["role"] not in ("driver", "passenger"):
            raise ValueError("Only people travelling in this ride can share their location")
        c.execute("insert into live_locations (match_id, user_id, lat, lng, accuracy_m) values (%s, %s, %s, %s, %s)"
                  " on conflict (match_id, user_id) do update set lat = excluded.lat, lng = excluded.lng,"
                  " accuracy_m = excluded.accuracy_m, updated_at = now()", (match_id, user_id, lat, lng, accuracy_m))
    return {"ok": True}


def live_locations(match_id: int, user_id: int) -> dict:
    """The driver sees every traveler; passengers and the vehicle owner see only the driver."""
    with db.conn() as c:
        who = _location_role(c, match_id, user_id)
        if who["status"] != "confirmed" or who["role"] is None:
            return {"locations": []}
        rows = c.execute("select l.user_id, u.name, t.role, l.lat, l.lng, l.accuracy_m, l.updated_at"
                         " from live_locations l join users u on u.id = l.user_id"
                         " join match_members mm on mm.match_id = l.match_id and mm.status <> 'cancelled'"
                         " join trips t on t.id = mm.trip_id and t.user_id = l.user_id"
                         " where l.match_id = %s and l.updated_at > now() - make_interval(secs => %s)"
                         " and (%s or t.role = 'driver') order by t.role, u.name",
                         (match_id, LOCATION_MAX_AGE_S, who["role"] == "driver")).fetchall()
    return {"locations": [_out(r) for r in rows]}
