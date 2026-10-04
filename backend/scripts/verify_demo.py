"""Walk the whole stage flow against the running API and print PASS or FAIL per step.

Books through the real MCP endpoint over the public tunnel, exactly as the ElevenLabs agent does,
then checks that the web accounts see it: Alex sees his trip and match, Maya and Jordan see the
match with their own place pending, Sam sees the booking to approve, and the match reaches
confirmed once all three accept and Sam approves. Restores demo state at the end.

No call, text or email is placed: this exercises booking and the web app only.

    python scripts/verify_demo.py            # uses PUBLIC_URL for the MCP hop
    python scripts/verify_demo.py --local    # uses the local API for the MCP hop too
"""
import asyncio
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

from app import config  # noqa: E402

import demo_accounts  # noqa: E402
import demo_state  # noqa: E402
import seed  # noqa: E402

API = os.getenv("DEMO_API_URL", "http://127.0.0.1:8000").rstrip("/")
results: list[bool] = []


def check(name: str, ok, detail="") -> bool:
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))
    return bool(ok)


def login(email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=30.0)
    r = c.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return c


def book_through_mcp(url: str, args: dict) -> dict:
    """Call request_ride over Streamable HTTP MCP, the same hop ElevenLabs makes."""
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async def go():
        async with httpx2.AsyncClient(headers={"X-Api-Key": config.API_TOKEN}, timeout=60) as http:
            async with Client(streamable_http_client(url, http_client=http)) as client:
                result = await client.call_tool("request_ride", args)
                return json.loads(result.content[0].text)
    return asyncio.run(go())


def main() -> int:
    local = "--local" in sys.argv
    mcp_url = (API if local else config.PUBLIC_URL).rstrip("/") + "/mcp"

    print("resetting to demo state")
    demo_state.main()
    window = seed.scenario_window()
    passwords = {name: (email, password) for _, name, email, password, _ in demo_accounts.ACCOUNTS}

    print(f"\nsigning in (API {API})")
    clients = {}
    for name in ("Alex", "Maya", "Jordan", "Sam"):
        email, password = passwords[name]
        try:
            clients[name] = login(email, password)
            check(f"{name} can sign in", True, email)
        except Exception as e:
            check(f"{name} can sign in", False, f"{type(e).__name__}")
            return report()

    alex = clients["Alex"].get("/me/dashboard").json()
    check("Alex starts with no trips", alex["trips"] == [], f"{len(alex['trips'])} trips")

    campus = ZoneInfo(config.TIMEZONE)
    tz_local = window[0].astimezone(campus).replace(tzinfo=None)
    tz_end = window[1].astimezone(campus).replace(tzinfo=None)
    print(f"\nbooking through MCP at {mcp_url}")
    t0 = time.monotonic()
    booked = book_through_mcp(mcp_url, {"user_id": 1, "destination": "Meijer",
                                        "earliest": tz_local.isoformat(), "latest": tz_end.isoformat(),
                                        "role": "driver", "needs_car": True})
    elapsed = time.monotonic() - t0
    check("request_ride booked a ride", "error" not in booked and booked.get("match_id"),
          booked.get("error") or f"trip {booked.get('trip_id')}, match {booked.get('match_id')}")
    check("booking answered in under 5 s", elapsed < 5, f"{elapsed:.2f}s")
    if "error" in booked:
        return report()
    match_id = booked["match_id"]

    again = book_through_mcp(mcp_url, {"user_id": 1, "destination": "Meijer",
                                      "earliest": tz_local.isoformat(), "latest": tz_end.isoformat(),
                                      "role": "driver", "needs_car": True})
    check("a repeated request returns the same trip", again.get("trip_id") == booked["trip_id"]
          and again.get("already_booked") is True, f"already_booked={again.get('already_booked')}")

    print("\nthe web app sees the call")
    alex = clients["Alex"].get("/me/dashboard").json()
    mine = next((m for m in alex["matches"] if m["id"] == match_id), None)
    check("Alex's dashboard shows the trip", len(alex["trips"]) == 1,
          alex["trips"][0]["dest_name"] if alex["trips"] else "none")
    check("Alex's dashboard shows the match", mine is not None)
    if not mine:
        return report()
    check("the match is Sam's Tesla", (mine["vehicle"] or {}).get("make_model") == "Tesla Model 3",
          (mine["vehicle"] or {}).get("make_model"))
    check("the match carries a price per person", mine["cost_per_person_cents"] > 0,
          f"${mine['cost_per_person_cents'] / 100:.2f} each")
    check("the match carries CO2 saved", (mine["impact"] or {}).get("kg_co2_avoided", 0) > 0,
          f"{(mine['impact'] or {}).get('kg_co2_avoided')} kg avoided, "
          f"{(mine['impact'] or {}).get('percent_reduction')}%")
    check("the group is Alex, Maya and Jordan",
          sorted(m["name"] for m in mine["members"] if m["status"] != "cancelled") == ["Alex", "Jordan", "Maya"],
          ", ".join(sorted(m["name"] for m in mine["members"])))

    for name in ("Maya", "Jordan"):
        board = clients[name].get("/me/dashboard").json()
        theirs = next((m for m in board["matches"] if m["id"] == match_id), None)
        me = next((x for x in (theirs or {}).get("members", []) if x["name"] == name), None)
        check(f"{name} sees the match with their place pending",
              theirs is not None and me and me["status"] == "pending", (me or {}).get("status"))

    sam = clients["Sam"].get("/me/dashboard").json()
    sam_match = next((m for m in sam["matches"] if m["id"] == match_id), None)
    booking = (sam_match or {}).get("booking")
    check("Sam sees the booking to approve", booking and booking["status"] == "requested",
          (booking or {}).get("status"))

    print("\neveryone confirms")
    for name in ("Alex", "Maya", "Jordan"):
        r = clients[name].post(f"/matches/{match_id}/accept", json={})
        check(f"{name} accepts", r.status_code == 200, f"HTTP {r.status_code}")
    state = clients["Alex"].get(f"/matches/{match_id}").json()
    check("still proposed until the owner approves", state["status"] == "proposed", state["status"])
    r = clients["Sam"].post(f"/bookings/{booking['id']}/approve")
    check("Sam approves the car", r.status_code == 200, f"HTTP {r.status_code}")
    final = clients["Alex"].get(f"/matches/{match_id}").json()
    check("the match is confirmed", final["status"] == "confirmed", final["status"])
    check("the confirmed match still reads out correctly", "Alex drives" in final["summary"],
          final["summary"][:90])

    print("\nresetting to demo state again")
    demo_state.main()
    after = login(*passwords["Alex"]).get("/me/dashboard").json()
    check("a reset leaves Alex clean and still able to sign in", after["trips"] == [],
          f"{len(after['trips'])} trips")
    return report()


def report() -> int:
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        from app import db
        db.close_pool()
