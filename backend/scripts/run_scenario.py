"""Definition-of-Done check through the HTTP API, in-process (TestClient runs the background
planning before each call returns). Resets the database first, once per planner mode.
    python scripts/run_scenario.py [--planner deterministic|gemini|both] [--write-fixtures]
Exits non-zero if any check fails. Never asserts exact distances or dollar amounts."""
import argparse
import json
import math
import sys
import traceback
import warnings
from collections import Counter
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("ignore", message=".*httpx2")   # starlette prefers httpx2; plain httpx still works
from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402
from scripts import seed  # noqa: E402

FIXTURES = ROOT / "fixtures"
results: list[bool] = []


def check(name: str, ok, detail="") -> bool:
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail not in ("", None, []) else ""))
    return bool(ok)


def api(c: TestClient, method: str, path: str, **kw):
    r = c.request(method, path, **kw)
    if r.status_code >= 400:
        raise AssertionError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def all_events(c) -> list[dict]:
    out, since = [], 0
    while True:
        page = api(c, "GET", f"/events?since={since}&limit=1000")
        out += page["events"]
        if not page["events"]:
            return out
        since = page["last_id"]


def cents_ok(m) -> bool:
    return m["cost_per_person_cents"] == math.ceil(m["raw_cost_cents"] / 3) and m["cost_per_person_cents"] * 3 == m["total_cost_cents"]


def run(mode: str) -> dict:
    """One full scenario. Returns representative responses for fixtures/api/."""
    print(f"\n=== planner: {mode} (gemini key {'set' if config.GEMINI_API_KEY else 'missing'},"
          f" maps {'live' if config.MAPS_SERVER_KEY else 'offline'}) ===")
    config.PLANNER = mode
    s = seed.reset()
    U, V = s["users"], s["vehicles"]
    w0 = s["window_start"].isoformat()
    c = TestClient(app)
    dump = {"health": api(c, "GET", "/health")}

    # 1. three trips to Meijer: Maya, Jordan, then Alex (driver, no car)
    trips = {}
    for name, role in (("Maya", "passenger"), ("Jordan", "passenger"), ("Alex", "driver")):
        r = api(c, "POST", "/trips", json={"user_id": U[name], "role": role, **s["destination"],
                                            "window_start": w0, "window_end": s["window_end"].isoformat()})
        trips[name] = r["trip"]
        dump.setdefault("trip_created", r)
    check("1 three trips created via POST /trips (Maya, Jordan, Alex driver without a car)",
          [t["id"] for t in trips.values()] == [1, 2, 3] and trips["Alex"]["needs_vehicle"] and r["planning"] == "queued")

    # 2. one match with all three, Alex's trip driving
    ms = api(c, "GET", "/trips/3/matches")
    dump["trip_matches"] = ms
    m = ms[0] if ms else {}
    roles = {x["trip_id"]: x["role"] for x in m.get("members", [])}
    check("2 GET /trips/3/matches: one match with all three, Alex's trip drives",
          len(ms) == 1 and roles == {1: "passenger", 2: "passenger", 3: "driver"} and m["driver_trip_id"] == 3,
          f"{len(ms)} matches, members {roles}")
    mid = m["id"]

    # 3. Tesla wins on CO2 although the Civic is closer and cheaper
    opts = {o["vehicle_id"]: o for o in m["reasons"]["vehicle_options"]}
    tesla, civic = opts[V["Tesla Model 3"]], opts[V["Honda Civic"]]
    check("3 vehicle is the Tesla Model 3 (EV)", (m["vehicle"] or {}).get("id") == V["Tesla Model 3"] and m["vehicle"]["fuel_type"] == "ev",
          (m["vehicle"] or {}).get("make_model"))
    check("3 Civic has less deadhead and a lower total cost, but more CO2",
          civic["deadhead_mi"] < tesla["deadhead_mi"] and civic["total_cost_cents"] < tesla["total_cost_cents"] and civic["kg_co2"] > tesla["kg_co2"],
          f"Tesla {tesla['kg_co2']} kg, {tesla['deadhead_mi']} mi deadhead, {tesla['total_cost_cents']}c; "
          f"Civic {civic['kg_co2']} kg, {civic['deadhead_mi']} mi, {civic['total_cost_cents']}c")
    check("3 reasons.vehicle is non-empty", m["reasons"]["vehicle"], m["reasons"]["vehicle"][:1])

    # 4. pickups and route
    check("4 pickup_order is trips 1 and 2, route.polyline present",
          sorted(m["pickup_order"]) == [1, 2] and m["route"]["polyline"], f"order {m['pickup_order']}, route {m['route']['source']}")

    # 5. money adds up, nobody has accepted yet
    check("5 cost_per_person = ceil(raw/3) and x3 = total; status proposed",
          cents_ok(m) and m["status"] == "proposed",
          f"raw {m['raw_cost_cents']}c, {m['cost_per_person_cents']}c each, total {m['total_cost_cents']}c, {m['status']}")

    # 6. impact (apply stores the assumptions block in its own column)
    imp, assumptions = m["impact"], m["impact"].get("assumptions") or m["assumptions"] or {}
    check("6 impact: shared/baseline miles, miles and kg CO2 avoided > 0, percent, assumptions with distance_source",
          all(k in imp for k in ("shared_miles", "baseline_miles", "percent_reduction"))
          and imp["miles_avoided"] > 0 and imp["kg_co2_avoided"] > 0 and assumptions.get("distance_source"),
          f"{imp['miles_avoided']} mi, {imp['kg_co2_avoided']} kg avoided, {imp['percent_reduction']}%, distances: {assumptions.get('distance_source')}")

    # 7. everyone accepts (twice: idempotent), Sam approves, match confirmed
    for _ in range(2):
        for name in ("Maya", "Jordan", "Alex"):
            acc = api(c, "POST", f"/matches/{mid}/accept", json={"user_id": U[name]})
    check("7 all three accepted (each twice), still proposed until the booking is approved",
          {x["status"] for x in acc["members"]} == {"accepted"} and acc["status"] == "proposed", acc["status"])
    bid = acc["booking"]["id"]
    for _ in range(2):
        ap = api(c, "POST", f"/bookings/{bid}/approve")
    check("7 Sam approves the Tesla booking -> match confirmed",
          acc["vehicle"]["owner_id"] == U["Sam"] and ap["booking"]["status"] == "approved" and ap["match"]["status"] == "confirmed",
          ap["match"]["status"])
    dump["match_detail"] = before = api(c, "GET", f"/matches/{mid}")

    # 9 runs before 8: the fixtures name the Tesla, which step 8 deactivates
    sub = {"{DEPART_BAD}": (s["window_start"] - timedelta(hours=4)).isoformat(), "{DEPART}": w0}

    def fixture(name):
        text = (FIXTURES / name).read_text()
        for token, value in sub.items():
            text = text.replace(token, value)
        return json.loads(text)

    r = api(c, "POST", "/planner/run", json={"plan": fixture("plan_valid.json"), "dry_run": True})
    check("9 fixtures/plan_valid.json is valid (dry run)", r["valid"] and not r["errors"], r["errors"])
    cases = fixture("plans_invalid.json")
    for case in cases:
        r = api(c, "POST", "/planner/run", json={"plan": case["plan"], "dry_run": True})
        missing = [e for e in case["expect"] if not any(e in err for err in r["errors"])]
        check(f"9 rejects invalid plan '{case['name']}'", not r["valid"] and not missing, missing or r["errors"][0])
        if len(r["errors"]) > len(dump.get("planner_dry_run_invalid", {}).get("errors", [])):
            dump["planner_dry_run_invalid"] = r
    check("9 dry runs changed nothing", api(c, "GET", f"/matches/{mid}")["updated_at"] == before["updated_at"])

    # 8. the Tesla is cancelled -> replan to the Leaf, match stays alive
    vc = api(c, "POST", f"/vehicles/{V['Tesla Model 3']}/cancel")
    dump["vehicle_cancel"] = vc
    rp = vc["replans"][0] if len(vc["replans"]) == 1 else {}
    d = rp.get("diff") or {}
    after = dump["match_detail_after_replan"] = api(c, "GET", f"/matches/{mid}")
    check("8 replacement vehicle is the Nissan Leaf (EV)",
          (after["vehicle"] or {}).get("id") == V["Nissan Leaf"] and after["vehicle"]["fuel_type"] == "ev", (after["vehicle"] or {}).get("make_model"))
    check("8 diff has before/after with different vehicles",
          d.get("cause") == "vehicle_cancelled" and (d["before"]["vehicle"] or {}).get("id") == V["Tesla Model 3"]
          and (d["after"]["vehicle"] or {}).get("id") == V["Nissan Leaf"] and after["last_change"]["cause"] == "vehicle_cancelled")
    check("8 numbers recomputed (CO2 and cost changed, cents still add up, new booking on the Leaf)",
          after["impact"]["kg_co2_shared"] != before["impact"]["kg_co2_shared"]
          and after["cost_per_person_cents"] != before["cost_per_person_cents"] and cents_ok(after)
          and after["booking"]["vehicle_id"] == V["Nissan Leaf"] and after["booking"]["status"] in ("requested", "approved"),
          f"{d['before']['kg_co2_shared']} -> {d['after']['kg_co2_shared']} kg, "
          f"{d['before']['cost_per_person_cents']}c -> {d['after']['cost_per_person_cents']}c each")
    check("8 match not at_risk", rp.get("status") not in (None, "at_risk") and after["status"] != "at_risk", after["status"])
    check("8 cancelling the Tesla again is a no-op", api(c, "POST", f"/vehicles/{V['Tesla Model 3']}/cancel")["replans"] == [])

    # 10. gemini mode: without a key every planner run falls back; with a key just report
    runs = dump["agent_runs"] = api(c, "GET", "/agent-runs?limit=500")
    # runs with no driver trip in scope skip Gemini (nothing to group) and log as deterministic
    planned = [x for x in runs if x["trigger"] != "manual_plan" and x["planner"] == "gemini"]
    if mode == "gemini" and not config.GEMINI_API_KEY:
        check("10 no GEMINI_API_KEY: every planner run is logged as gemini with fallback_used",
              planned and all(x["planner"] == "gemini" and x["fallback_used"] for x in planned), f"{len(planned)} runs")
    elif mode == "gemini":
        used = sum(not x["fallback_used"] for x in planned)
        print(f"  INFO  10 Gemini's own plan was used in {used} of {len(planned)} planner runs (the rest fell back)")

    # 11. events for every step, one agent_runs row per planning run
    evs = dump["events"] = all_events(c)
    kinds = Counter(e["kind"] for e in evs)
    need = ["trip_created", "planning_started", "plan_validated", "match_created", "booking_requested", "member_accepted",
            "booking_approved", "match_confirmed", "vehicle_cancelled", "match_updated", "planning_finished"]
    need += ["fallback_used"] if mode == "gemini" and not config.GEMINI_API_KEY else []
    check("11 events cover every step", not [k for k in need if not kinds[k]], [k for k in need if not kinds[k]])
    check("11 accept and approve logged once each (idempotent)", kinds["member_accepted"] == 3 and kinds["booking_approved"] == 1,
          f"{kinds['member_accepted']} accepted, {kinds['booking_approved']} approved")
    expected = 3 + 1 + len(cases) + 1   # trips, plan_valid, invalid fixtures, Tesla replan
    check("11 one agent_runs row per planning run", len(runs) == kinds["planning_started"] == expected,
          f"{len(runs)} rows, {kinds['planning_started']} planning_started, expected {expected}")
    dump["impact"] = api(c, "GET", "/impact")
    return dump


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--planner", choices=["deterministic", "gemini", "both"], default="both")
    ap.add_argument("--write-fixtures", action="store_true")
    args = ap.parse_args()
    modes = ["deterministic", "gemini"] if args.planner == "both" else [args.planner]
    for n, mode in enumerate(modes):
        try:
            dump = run(mode)
        except Exception:
            check(f"{mode} scenario ran to the end", False, traceback.format_exc(limit=3).strip().splitlines()[-1])
            traceback.print_exc()
            continue
        if args.write_fixtures and n == 0:
            out = FIXTURES / "api"
            out.mkdir(exist_ok=True)
            for name, body in dump.items():
                (out / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n")
            print(f"  wrote {len(dump)} files to {out}")
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
