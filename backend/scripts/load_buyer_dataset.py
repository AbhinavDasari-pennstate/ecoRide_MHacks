"""Upsert the simulated buyer dataset and its model outputs into the buyer_* tables.

fixtures/buyer_dataset.json fills buyer_trips and buyer_events.
fixtures/buyer_models.json fills buyer_model_runs, buyer_trip_scores and buyer_driver_risk, so a
reset restores the scores without retraining and the API never needs scikit-learn.

Idempotent and non-destructive: rows are keyed by their fixture ids; nothing else is deleted.
    python scripts/load_buyer_dataset.py

Regenerate the model fixture with:
    python scripts/train_buyer_models.py        (needs requirements-dev.txt)
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "buyer_dataset.json"
MODELS = Path(__file__).resolve().parents[1] / "fixtures" / "buyer_models.json"


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


def load_models() -> tuple[int, int, int]:
    """Restore the committed model outputs. Returns (runs, trip scores, drivers)."""
    if not MODELS.exists():
        return 0, 0, 0
    bundle = json.loads(MODELS.read_text(encoding="utf-8"))
    runs = [{"name": r["name"], "kind": r["kind"], "trained_at": bundle["trained_at"],
             "library": r["library"], "dataset_rows": bundle["dataset_rows"],
             "random_seed": r["random_seed"], "features": db.J(r["features"]),
             "metrics": db.J(r["metrics"]), "params": db.J(r["params"]), "notes": r["notes"]}
            for r in bundle["runs"]]
    scores = [{"trip_id": s["trip_id"], "features": db.J(s["features"]),
               "anomaly_score": s["anomaly_score"], "anomaly_flagged": s["anomaly_flagged"],
               "risk_probability": s["risk_probability"],
               "predicted_kwh_per_mi": s["predicted_kwh_per_mi"],
               "actual_kwh_per_mi": s["actual_kwh_per_mi"], "scored_by": s["scored_by"]}
              for s in bundle["trip_scores"]]
    drivers = bundle["driver_risk"]
    with db.conn() as c:
        db.lock(c)
        with c.cursor() as cur:
            cur.executemany(
                "insert into buyer_model_runs (name, kind, trained_at, library, dataset_rows,"
                " random_seed, features, metrics, params, notes) values (%(name)s, %(kind)s,"
                " %(trained_at)s, %(library)s, %(dataset_rows)s, %(random_seed)s, %(features)s,"
                " %(metrics)s, %(params)s, %(notes)s) on conflict (name) do update set"
                " kind = excluded.kind, trained_at = excluded.trained_at, library = excluded.library,"
                " dataset_rows = excluded.dataset_rows, random_seed = excluded.random_seed,"
                " features = excluded.features, metrics = excluded.metrics, params = excluded.params,"
                " notes = excluded.notes", runs)
            cur.executemany(
                "insert into buyer_trip_scores (trip_id, features, anomaly_score, anomaly_flagged,"
                " risk_probability, predicted_kwh_per_mi, actual_kwh_per_mi, scored_by)"
                " values (%(trip_id)s, %(features)s, %(anomaly_score)s, %(anomaly_flagged)s,"
                " %(risk_probability)s, %(predicted_kwh_per_mi)s, %(actual_kwh_per_mi)s, %(scored_by)s)"
                " on conflict (trip_id) do update set features = excluded.features,"
                " anomaly_score = excluded.anomaly_score, anomaly_flagged = excluded.anomaly_flagged,"
                " risk_probability = excluded.risk_probability,"
                " predicted_kwh_per_mi = excluded.predicted_kwh_per_mi,"
                " actual_kwh_per_mi = excluded.actual_kwh_per_mi, scored_by = excluded.scored_by,"
                " scored_at = now()", scores)
            cur.executemany(
                "insert into buyer_driver_risk (driver_id, trips, risk_score, mean_probability)"
                " values (%(driver_id)s, %(trips)s, %(risk_score)s, %(mean_probability)s)"
                " on conflict (driver_id) do update set trips = excluded.trips,"
                " risk_score = excluded.risk_score, mean_probability = excluded.mean_probability,"
                " computed_at = now()", drivers)
    return len(runs), len(scores), len(drivers)


if __name__ == "__main__":
    db.apply_schema()
    try:
        print("Loaded %d trips, %d events" % load())
        print("Loaded %d model runs, %d trip scores, %d driver scores" % load_models())
    finally:
        db.close_pool()
