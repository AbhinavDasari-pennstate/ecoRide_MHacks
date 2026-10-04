"""Turn a confirmed ride into one simulated telemetry trip for the data portal.

The distance comes from the planned route, so the trip corresponds to a real booking. Everything
else, the duration, the energy and the driving events, is generated from a seed derived from the
match id. That makes it reproducible: the same match always produces the same trip. It is not
measured, and no device recorded it.

No name, phone or email is stored. The driver is a short anonymous code derived from the user id.
"""
import hashlib
import json
import logging
import random
from datetime import timedelta

from app import buyer_models as bm, config, db

log = logging.getLogger(__name__)

# Thresholds carried over from the fixture generator, so a generated trip is flagged on the same
# rules as the rest of the dataset.
RULES = [("hard_brake", 0.30, "deceleration"),
         ("rapid_acceleration", 0.25, "acceleration"),
         ("sharp_turn", 0.30, "lateral acceleration")]
REVIEW_MARGIN = 0.10
MODEL_NAMES = (bm.RISK, bm.ENERGY)


def anonymous_driver(user_id: int) -> str:
    """A stable code for a person, carrying no name, number or address."""
    return "BK-" + hashlib.sha256(f"eride-driver-{user_id}".encode()).hexdigest()[:4].upper()


def _generate(match: dict, miles: float) -> tuple[dict, list[dict]]:
    """Deterministic from the match id. Same match in, same trip out."""
    rng = random.Random(int(match["id"]))
    trip_id = f"BK-{int(match['id']):04d}"
    minutes = max(5, int(round(miles * 2.2 + 5 + rng.uniform(-3, 3))))
    kwh_per_mile = round(0.23 + rng.uniform(0.0, 0.06), 4)
    events = []
    for index, (kind, threshold, measure) in enumerate(RULES):
        value = round(threshold - 0.06 + rng.uniform(0.0, 0.22), 2)
        if value <= threshold:
            continue
        review_at = round(threshold + REVIEW_MARGIN, 2)
        offset = max(1, int(round(minutes * 60 * (index + 1) / 4)))
        events.append({
            "id": f"{trip_id}-E{index + 1}", "tripId": trip_id, "type": kind,
            "offsetSeconds": offset,
            "severity": "Review" if value >= review_at else "Watch",
            "detail": (f"Peak simulated {measure} reached {value:.2f} g, above the "
                       f"{threshold:.2f} g demo threshold. Review starts at {review_at:.2f} g; "
                       f"lower flagged values are Watch."),
            "value": value, "unit": "g", "threshold": threshold,
        })
    trip = {"id": trip_id, "miles": round(miles, 2), "durationMinutes": minutes,
            "estimatedEnergyKwh": round(miles * kwh_per_mile, 2)}
    return trip, events


def _score(c, trip_id: str, features: dict) -> None:
    """Score with the committed parameters. Anomaly is optional and may stay unscored."""
    rows = c.execute("select name, params from buyer_model_runs where name = any(%s::text[])",
                     (list(MODEL_NAMES),)).fetchall()
    params = {r["name"]: r["params"] for r in rows}
    risk = bm.risk_probability(features, params[bm.RISK]) if bm.RISK in params else None
    energy = bm.predicted_kwh_per_mi(features, params[bm.ENERGY]) if bm.ENERGY in params else None
    score, flagged = bm.anomaly_score(features)
    scored_by = "unscored" if risk is None and energy is None and score is None else "runtime"
    c.execute("insert into buyer_trip_scores (trip_id, features, anomaly_score, anomaly_flagged,"
              " risk_probability, predicted_kwh_per_mi, actual_kwh_per_mi, scored_by)"
              " values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (trip_id) do update set"
              " features = excluded.features, anomaly_score = excluded.anomaly_score,"
              " anomaly_flagged = excluded.anomaly_flagged,"
              " risk_probability = excluded.risk_probability,"
              " predicted_kwh_per_mi = excluded.predicted_kwh_per_mi,"
              " actual_kwh_per_mi = excluded.actual_kwh_per_mi, scored_by = excluded.scored_by,"
              " scored_at = now()",
              (trip_id, db.J(features), score, flagged, risk, energy,
               features.get("kwh_per_mi"), scored_by))


def record_confirmed_ride(c, match_id: int) -> str | None:
    """One telemetry trip and one owner payout per confirmed match. Returns the trip id or None.

    Runs inside the caller's transaction, so a ride that rolls back leaves no telemetry behind.
    Safe to call again: the unique index on match_id means a replan or a repeated accept cannot
    insert a second trip."""
    try:
        # A savepoint, so a telemetry fault rolls back only this work and the ride still confirms.
        with c.transaction():
            return _write(c, match_id)
    except Exception as e:
        log.warning("telemetry for match %s failed (%s); the ride is unaffected",
                    match_id, type(e).__name__)
        return None


def _write(c, match_id: int) -> str | None:
    row = c.execute("select m.id, m.depart_time, m.vehicle_id, m.impact, t.user_id,"
                    " v.owner_id from matches m join trips t on t.id = m.driver_trip_id"
                    " left join vehicles v on v.id = m.vehicle_id where m.id = %s",
                    (match_id,)).fetchone()
    if not row:
        return None
    existing = c.execute("select id from buyer_trips where match_id = %s", (match_id,)).fetchone()
    if existing:
        c.execute("update buyer_trips set voided = false where id = %s", (existing["id"],))
        return existing["id"]

    impact = row["impact"] or {}
    if isinstance(impact, str):
        impact = json.loads(impact)
    miles = float(impact.get("shared_miles") or 0.0)
    if miles <= 0:
        return None
    trip, events = _generate(dict(row), miles)
    driver = anonymous_driver(row["user_id"])
    started = row["depart_time"]
    c.execute("insert into buyer_trips (id, driver_id, started_at, miles, duration_minutes,"
              " estimated_energy_kwh, source, simulated, match_id, vehicle_id)"
              " values (%s, %s, %s, %s, %s, %s, 'booking', true, %s, %s)",
              (trip["id"], driver, started, trip["miles"], trip["durationMinutes"],
               trip["estimatedEnergyKwh"], match_id, row["vehicle_id"]))
    for event in events:
        c.execute("insert into buyer_events (id, trip_id, driver_id, type, at, offset_seconds,"
                  " severity, detail, value, unit, threshold)"
                  " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                  (event["id"], trip["id"], driver, event["type"],
                   started + timedelta(seconds=event["offsetSeconds"]), event["offsetSeconds"],
                   event["severity"], event["detail"], event["value"], event["unit"],
                   event["threshold"]))
    features = bm.features_for({**trip, "startedAt": started.isoformat()}, events)
    _score(c, trip["id"], features)
    if row["owner_id"]:
        c.execute("insert into owner_data_earnings (match_id, owner_id, vehicle_id,"
                  " buyer_trip_id, amount_cents) values (%s, %s, %s, %s, %s)"
                  " on conflict (match_id) do nothing",
                  (match_id, row["owner_id"], row["vehicle_id"], trip["id"],
                   config.DEMO_DATA_PAYOUT_CENTS))
    db.event(c, "telemetry_recorded", {"match_id": match_id, "buyer_trip_id": trip["id"],
                                       "events": len(events), "simulated": True})
    return trip["id"]


def void_for_match(c, match_id: int) -> None:
    """A cancelled ride keeps its generated trip, marked rather than deleted, and loses the payout."""
    c.execute("update buyer_trips set voided = true where match_id = %s", (match_id,))
    c.execute("delete from owner_data_earnings where match_id = %s", (match_id,))
