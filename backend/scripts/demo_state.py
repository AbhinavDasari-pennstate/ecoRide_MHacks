"""Restore the live-call demo in one command: the seeded users and vehicles, with Maya and Jordan
already waiting for Meijer in the scenario window, web logins for everyone on stage, and no other
trips or matches. Run this before each phone call; it is idempotent.
The caller (DEMO_PHONES) posts the driver trip on the call itself, which is what forms the match.
    python scripts/demo_state.py"""
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import apply, config  # noqa: E402

import demo_accounts  # noqa: E402  (web logins on the seeded users)
import seed  # noqa: E402  (scripts/seed.py: schema, 7 users, 4 vehicles, no trips)

TZ = ZoneInfo(config.TIMEZONE)
WAITING = [("Maya", 2), ("Jordan", 3)]   # passengers; ids come from seed.USERS


def main() -> None:
    out = seed.reset()                   # truncates trips/matches too, so stray test trips go away
    start, end = out["window_start"], out["window_end"]
    for name, user_id in WAITING:
        trip = apply.create_trip({"user_id": user_id, "role": "passenger", "dest_name": "Meijer",
                                  "window_start": start, "window_end": end, "party_size": 1})
        print(f"  waiting passenger: {name} (user {user_id}) -> trip {trip['id']}, {trip['dest_name']}")
    # No planning run: with no driver trip there is nothing to group, and leaving /agent-runs empty
    # means the first row on stage is the phone call itself.
    print(f"  window: {start.astimezone(TZ):%a %Y-%m-%d %I:%M %p}-{end.astimezone(TZ):%I:%M %p} {config.TIMEZONE}")
    # seed.py no longer keeps per-vehicle hours on the tuple; every demo car shares one long window
    avail_start, avail_end = seed.availability()
    print(f"  vehicles bookable {avail_start.astimezone(TZ):%a %Y-%m-%d %I:%M %p}"
          f" -> {avail_end.astimezone(TZ):%a %Y-%m-%d %I:%M %p} {config.TIMEZONE}")
    for name, vid in out["vehicles"].items():
        owner = seed.USERS[seed.VEHICLES[vid - 1][0] - 1][0]
        print(f"  vehicle {vid}: {owner}'s {name}")
    # seed.reset() truncates users with cascade, so the logins go back on afterwards.
    accounts = demo_accounts.create()
    demo_accounts.write_file(accounts)
    caller = ", ".join(f"{n}={p}" for n, p in seed.DEMO_PHONES.items()) or "(DEMO_PHONES is empty)"
    print(f"\nReady. Caller: {caller}")
    print("Dial the Twilio number and ask to drive to Meijer in that window.")
    demo_accounts.report(accounts)


if __name__ == "__main__":
    main()
