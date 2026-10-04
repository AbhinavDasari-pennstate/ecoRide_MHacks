"""Restore the live-call demo: the seeded users and vehicles, with Maya and Jordan already waiting for
Meijer in the scenario window and no other trips. Run this before each phone call; it is idempotent.
The caller (DEMO_PHONES) posts the driver trip on the call itself, which is what forms the match.
    python scripts/demo_state.py"""
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import apply, config  # noqa: E402

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
    for name, vid in out["vehicles"].items():
        owner = seed.USERS[seed.VEHICLES[vid - 1][0] - 1][0]
        t0, t1 = seed.VEHICLES[vid - 1][6]
        print(f"  vehicle {vid}: {owner}'s {name}, free {t0:%I:%M %p}-{t1:%I:%M %p}")
    caller = ", ".join(f"{n}={p}" for n, p in seed.DEMO_PHONES.items()) or "(DEMO_PHONES is empty)"
    print(f"\nReady. Caller: {caller}")
    print("Dial the Twilio number and ask to drive to Meijer in that window.")


if __name__ == "__main__":
    main()
