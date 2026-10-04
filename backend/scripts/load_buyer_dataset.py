"""Upsert the simulated buyer dataset (fixtures/buyer_dataset.json) into buyer_trips / buyer_events.

Idempotent and non-destructive: rows are keyed by their fixture ids; nothing else is deleted.
    python scripts/load_buyer_dataset.py
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "buyer_dataset.json"


def load() -> tuple[int, int]:
    trips = json.loads(FIXTURE.read_text(encoding="utf-8"))["demoTrips"]
    events = [e for t in trips for e in t["events"]]
    with db.conn() as c:
        db.lock(c)
        with c.cursor() as cur:
            cur.executemany(
                "insert into buyer_trips (id, driver_id, started_at, miles, duration_minutes, estimated_energy_kwh)"
                " values (%(id)s, %(driverId)s, %(startedAt)s, %(miles)s, %(durationMinutes)s, %(estimatedEnergyKwh)s)"
                " on conflict (id) do update set driver_id = excluded.driver_id, started_at = excluded.started_at,"
                " miles = excluded.miles, duration_minutes = excluded.duration_minutes,"
                " estimated_energy_kwh = excluded.estimated_energy_kwh", trips)
            cur.executemany(
                "insert into buyer_events (id, trip_id, driver_id, type, at, offset_seconds, severity, detail, value,"
                " unit, threshold) values (%(id)s, %(tripId)s, %(driverId)s, %(type)s, %(timestamp)s,"
                " %(offsetSeconds)s, %(severity)s, %(detail)s, %(value)s, %(unit)s, %(threshold)s)"
                " on conflict (id) do update set trip_id = excluded.trip_id, driver_id = excluded.driver_id,"
                " type = excluded.type, at = excluded.at, offset_seconds = excluded.offset_seconds,"
                " severity = excluded.severity, detail = excluded.detail, value = excluded.value,"
                " unit = excluded.unit, threshold = excluded.threshold", events)
    return len(trips), len(events)


if __name__ == "__main__":
    db.apply_schema()
    try:
        print("Loaded %d trips, %d events" % load())
    finally:
        db.close_pool()
