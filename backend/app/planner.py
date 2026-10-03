"""Grouping planner. Gemini drafts who rides with whom (and why); code fills in the vehicle and
pickup order (core.complete) and checks the result (core.validate). Validator errors go back to
Gemini for a retry; anything else that goes wrong falls back to core.fallback_plan.
draft() and explain() never raise."""
from __future__ import annotations

import functools
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from google import genai
from google.genai import types
from pydantic import BaseModel

from app import config, core

EXPLAIN_TIMEOUT_S = 8
TRANSIENT = {429, 500, 503, 504}   # overloaded or rate-limited: worth another try, unlike 400/401/403
_NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

SYSTEM = """You group campus ride-share trips. Decide who rides with whom and which driver trip drives.
Code then picks the vehicle and the pickup order, computes every number, and checks your plan.

Objectives, in priority order:
1. Minimize total kg CO2 and vehicle-miles across all requests: fewer, fuller vehicles beat more vehicles.
2. Keep every group feasible:
   - group size (sum of party_size, driver included) fits the seats of an active, free vehicle,
     or own_car_seats when the driver has needs_vehicle false;
   - depart_time is inside every member's window;
   - each passenger adds at most their detour_limit_mi to the driver's route (use origin_mi);
   - each passenger's destination is within half a mile of the driver's (use destination_mi).
3. Then lower cost and shorter travel time.

Rules:
- Use only trip ids from the context. Every trip appears exactly once: in one group or in unassigned.
- driver_trip_id must be a trip with role "driver"; passenger_trip_ids must be trips with role "passenger".
- depart_time is ISO 8601 in UTC, for example 2026-01-31T18:45:00Z.
- When no feasible group exists for a trip, put it in unassigned with a short reason.
- rationale: two or three short reasons for the grouping, in words.
- Never write figures (no digits at all) in rationale or reasons. Code computes all costs, miles and CO2.
- Do not choose a vehicle or a pickup order; code does that.
- If "replan" is present, an existing match changed (see its cause). Keep its trips going: rebuild the
  group around the change if any feasible alternative exists, otherwise mark the trips unassigned.
- If the validator rejects your plan, fix every listed error and return the full plan again."""

EXPLAIN_SYSTEM = """Write two to four plain sentences for the riders explaining this shared trip: who drives whom,
which vehicle and why (its CO2 compared with the alternative), and what sharing saves.
Use only the facts given. Any number you write must appear in the facts; cost_per_person_cents is in cents,
so write it in dollars (820 becomes $8.20). No markdown, no lists."""


# ---------------------------------------------------------------- Gemini output schema

class _GroupOut(BaseModel):
    driver_trip_id: int
    passenger_trip_ids: list[int]
    depart_time: str               # ISO 8601 UTC; a plain string keeps the Gemini schema simple
    rationale: list[str]


class _UnassignedOut(BaseModel):
    trip_id: int
    reason: str


class _PlanOut(BaseModel):
    groups: list[_GroupOut]
    unassigned: list[_UnassignedOut]


# ---------------------------------------------------------------- helpers

def _numbers(s: str) -> list[str]:
    return _NUM.findall(re.sub(r"CO2", "", s, flags=re.I))     # "CO2" is a word, not a figure


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)   # naive = UTC, as the prompt asks


def _err(e: Exception) -> str:
    """Exception type plus the HTTP code/status for API errors (e.g. 401 UNAUTHENTICATED = bad key).
    Never the message: it is not needed to diagnose and keeps anything sensitive out of logs."""
    code, status = getattr(e, "code", None), getattr(e, "status", None)
    return f"error: {type(e).__name__}" + (f" {code} {status}" if code else "")


def _live(ctx: core.Ctx) -> list[core.Trip]:
    return sorted((t for t in ctx.trips.values() if t.status != "cancelled"), key=lambda t: t.id)


def _msg(role: str, text: str) -> dict:
    return {"role": role, "parts": [{"text": text}]}


@functools.cache
def _default_client():
    return genai.Client(api_key=config.GEMINI_API_KEY)


# ponytail: a timed-out call keeps its worker until the http timeout ends it; fine for one process
_pool = ThreadPoolExecutor(max_workers=4)


def _call(client, contents: list, timeout_s: float, model: str | None = None, **cfg) -> str:
    """One generate_content call with a hard deadline (raises TimeoutError past it). The SDK retries
    a transient error once inside that deadline (by default it never retries)."""
    conf = types.GenerateContentConfig(
        temperature=config.GEMINI_TEMPERATURE,
        thinking_config=types.ThinkingConfig(thinking_level=config.GEMINI_THINKING_LEVEL),
        # the http timeout only frees the worker; the deadline below is the real limit
        http_options=types.HttpOptions(timeout=int(max(timeout_s, 10) * 1000), retry_options=types.HttpRetryOptions(
            attempts=2, initial_delay=0.5, http_status_codes=sorted(TRANSIENT))), **cfg)
    fut = _pool.submit(client.models.generate_content, model=model or config.GEMINI_MODEL, contents=contents, config=conf)
    return fut.result(timeout=timeout_s).text or ""


def _context(ctx: core.Ctx, replan: dict | None) -> str:
    trips = _live(ctx)
    return json.dumps({
        "trips": [{
            "id": t.id, "role": t.role, "needs_vehicle": t.needs_vehicle, "party_size": t.party_size,
            "window_start": _iso(t.window_start), "window_end": _iso(t.window_end), "destination": t.dest_name,
            "solo_mi": round(core.solo_mi(ctx, t), 2), "detour_limit_mi": round(core.detour_limit(ctx, t), 2),
        } for t in trips],
        # ponytail: full pairwise matrices; fine while the scope is one destination's nearby trips
        "origin_mi": {t.id: {u.id: round(ctx.dist(t.origin, u.origin), 2) for u in trips if u is not t} for t in trips},
        "destination_mi": {t.id: {u.id: round(ctx.dist(t.dest, u.dest), 2) for u in trips if u is not t} for t in trips},
        "vehicles": [{
            "id": v.id, "make_model": v.make_model, "fuel_type": v.fuel_type, "seats": v.seats,
            "available": [_iso(v.avail_start), _iso(v.avail_end)],
            "booked": [[_iso(b.start_ts), _iso(b.end_ts)] for b in ctx.bookings
                       if b.vehicle_id == v.id and b.status in ("requested", "approved")],
            "kg_co2_per_mile": round(core.co2_kg(v, 1.0), 3),
        } for v in ctx.vehicles.values() if v.active],
        "own_car_seats": config.OWN_CAR_SEATS,
        "replan": replan,
    }, default=str)


def _to_plan(text: str) -> core.Plan:
    """Gemini JSON -> core.Plan. Strings with figures are dropped: numbers come from code only."""
    out = _PlanOut.model_validate_json(text)
    return core.Plan(
        groups=[core.Group(driver_trip_id=g.driver_trip_id, passenger_trip_ids=g.passenger_trip_ids,
                           depart_time=_utc(g.depart_time), rationale=[r for r in g.rationale if not _numbers(r)])
                for g in out.groups],
        unassigned=[core.Unassigned(trip_id=u.trip_id, reason="no feasible group found" if _numbers(u.reason) else u.reason)
                    for u in out.unassigned])


def _dropped(draft: core.Plan, plan: core.Plan, opts: dict, ctx: core.Ctx) -> list[str]:
    """complete() unassigns groups with no feasible vehicle, so e.g. a bad depart_time never reaches
    validate(). For a Gemini draft that is a rejection: re-check each such group with its best
    (infeasible) vehicle so Gemini hears why."""
    kept = {g.driver_trip_id for g in plan.groups}
    errs = []
    for g in draft.groups:
        if g.driver_trip_id in kept or not opts.get(g.driver_trip_id):
            continue
        driver = ctx.trips[g.driver_trip_id]
        g = g.model_copy(update={"vehicle_id": opts[g.driver_trip_id][0]["vehicle_id"], "pickup_order":
                                 core.nearest_neighbor_order(ctx, driver, [ctx.trips[i] for i in g.passenger_trip_ids])})
        errs += core.validate(core.Plan(groups=[g]), ctx) or [
            f"driver trip {driver.id}: no feasible vehicle is left for this group after the other groups"]
    return errs


def _missing(plan: core.Plan, ctx: core.Ctx) -> list[str]:
    seen = {i for g in plan.groups for i in (g.driver_trip_id, *g.passenger_trip_ids)} | {u.trip_id for u in plan.unassigned}
    return [f"trip {t.id} is missing: put it in a group or in unassigned with a reason" for t in _live(ctx) if t.id not in seen]


# ---------------------------------------------------------------- planners

def draft(ctx: core.Ctx, trigger: str, mode: str | None = None, replan: dict | None = None,
          client=None) -> tuple[core.Plan, dict, dict]:
    """-> (validated plan, vehicle_options by driver_trip_id, run_log for db.agent_run)."""
    t0 = time.monotonic()
    mode = mode or config.PLANNER
    skip = mode == "gemini" and not any(t.role == "driver" for t in _live(ctx))
    if skip:
        mode = "deterministic"      # no driver trip in scope: no group is possible, nothing for Gemini to decide
    log = {"trigger": trigger, "planner": "gemini" if mode == "gemini" else "deterministic", "tool_calls": [],
           "raw_output": [], "validator_errors": [], "retries": 0, "latency_ms": 0, "fallback_used": False}
    if skip:
        log["tool_calls"].append({"attempt": 0, "outcome": "skipped Gemini: no driver trip in scope"})
    out = _gemini(ctx, replan, client, log, t0) if mode == "gemini" else None
    if out is None:
        log["fallback_used"] = mode == "gemini"
        out = _fallback(ctx, log)
    log["latency_ms"] = int((time.monotonic() - t0) * 1000)
    return out[0], out[1], log


def _gemini(ctx, replan, client, log, t0):
    """Up to 1 + PLANNER_MAX_RETRIES attempts inside PLANNER_TIMEOUT_S total. None = use the fallback."""
    if not config.GEMINI_API_KEY:
        log["tool_calls"].append({"attempt": 0, "outcome": "no GEMINI_API_KEY"})
        return None
    contents = [_msg("user", "Plan these trips.\n" + _context(ctx, replan))]
    model = config.GEMINI_MODEL
    for n in range(1 + config.PLANNER_MAX_RETRIES):
        left = config.PLANNER_TIMEOUT_S - (time.monotonic() - t0)
        if left <= 0:
            break
        log["retries"] = n
        t = time.monotonic()
        try:
            text = _call(client or _default_client(), contents, left, model, system_instruction=SYSTEM,
                         response_mime_type="application/json", response_schema=_PlanOut)
        except Exception as e:
            log["tool_calls"].append({"attempt": n, "model": model, "ms": int((time.monotonic() - t) * 1000),
                                      "outcome": "timeout" if isinstance(e, TimeoutError) else _err(e)})
            if getattr(e, "code", None) in TRANSIENT and config.GEMINI_BACKUP_MODEL and model != config.GEMINI_BACKUP_MODEL:
                model = config.GEMINI_BACKUP_MODEL   # still overloaded after the SDK's retry: switch models
                continue
            return None             # timeout, bad key, bad request: another try would not help
        log["raw_output"].append(text)
        try:
            drafted = _to_plan(text)
            plan, opts = core.complete(drafted, ctx)
            errs = core.validate(plan, ctx) + _dropped(drafted, plan, opts, ctx) + _missing(plan, ctx)
        except Exception as e:      # bad JSON, schema mismatch, bad timestamp
            errs = [f"output does not match the schema: {str(e)[:300]}"]
        log["validator_errors"].append(errs)
        log["tool_calls"].append({"attempt": n, "model": model, "ms": int((time.monotonic() - t) * 1000),
                                  "outcome": "invalid" if errs else "valid"})
        if not errs:
            return plan, opts
        contents += [_msg("model", text), _msg("user", "The validator rejected that plan:\n- " + "\n- ".join(errs)
                                               + "\nFix every error and return the full plan again.")]
    return None


def _fallback(ctx: core.Ctx, log: dict) -> tuple[core.Plan, dict]:
    try:
        plan, opts = core.complete(core.fallback_plan(ctx), ctx)
        errs = core.validate(plan, ctx)
    except Exception as e:          # a core bug must not take planning down
        errs = [f"fallback planner crashed: {type(e).__name__}: {e}"]
    if not errs:
        return plan, opts
    log["validator_errors"].append(errs)
    log["tool_calls"].append({"attempt": "fallback", "outcome": "invalid"})
    return core.Plan(unassigned=[core.Unassigned(trip_id=t.id, reason="no valid plan could be built")
                                 for t in _live(ctx)]), {}


# ---------------------------------------------------------------- explanation

def _numbers_ok(text: str, facts: dict) -> bool:
    """Every number in text must be a fact value (rounded to 0-2 decimals; *_cents also in dollars)
    or appear inside a fact string, e.g. a vehicle name."""
    ok = set()
    for k, v in facts.items():
        for x in v if isinstance(v, list) else [v]:
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                ok |= {round(n, d) for n in ([x, x / 100] if k.endswith("_cents") else [x]) for d in (0, 1, 2)}
            elif x is not None:
                ok |= {float(s.replace(",", "")) for s in _numbers(str(x))}
    # ponytail: numbers spelled as words ("three") are not checked
    return all(float(s.replace(",", "")) in ok for s in _numbers(text))


def explain(facts: dict, client=None) -> str:
    """2-4 sentences for riders. Gemini only when EXPLAIN=gemini and a key is set, and only if every
    number it writes comes from facts; otherwise the code template."""
    template = core.template_explanation(facts)
    if config.EXPLAIN != "gemini" or not config.GEMINI_API_KEY:
        return template
    try:
        text = _call(client or _default_client(), [_msg("user", json.dumps(facts, default=str))],
                     EXPLAIN_TIMEOUT_S, system_instruction=EXPLAIN_SYSTEM).strip()
    except Exception:
        return template
    return text if text and _numbers_ok(text, facts) else template
