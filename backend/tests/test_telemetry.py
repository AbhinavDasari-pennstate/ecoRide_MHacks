"""A confirmed ride produces exactly one simulated telemetry trip and one owner payout.

The dedupe matters most: replans, repeated accepts and repeated approvals all run through
_maybe_confirm, so without the unique index on match_id the portal would fill with duplicates.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import apply, buyer_models as bm, config, db, telemetry
from app.main import app
from scripts import seed
from test_database import database, postgres, trip  # noqa: F401  (pytest fixtures)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import demo_accounts  # noqa: E402


def confirmed(database, approve=True):
    for user_id in (2, 3):
        trip(database, user_id, "passenger")
    driver = trip(database, 1)
    match = apply.get_match(apply.run_planning("test", driver["id"])["match_ids"][0])
    for user_id in (1, 2, 3):
        apply.accept(match["id"], user_id)
    if approve:
        return apply.approve_booking(match["booking"]["id"])["match"]
    return apply.get_match(match["id"])


def booking_trips(include_voided=False):
    where = "" if include_voided else " and not voided"
    with db.conn() as c:
        return c.execute(f"select * from buyer_trips where source = 'booking'{where}"
                         " order by id").fetchall()


def earnings():
    with db.conn() as c:
        return c.execute("select * from owner_data_earnings order by match_id").fetchall()


# ---------------------------------------------------------------- generation

def test_a_confirmed_ride_creates_one_telemetry_trip(database):
    match = confirmed(database)
    assert match["status"] == "confirmed"
    trips = booking_trips()
    assert len(trips) == 1
    row = trips[0]
    assert row["id"] == f"BK-{match['id']:04d}"
    assert row["source"] == "booking" and row["simulated"] is True and row["voided"] is False
    assert row["match_id"] == match["id"] and row["vehicle_id"] == match["vehicle_id"]
    # The distance is the planned route, so the trip corresponds to a real booking.
    assert row["miles"] == pytest.approx(match["impact"]["shared_miles"], abs=0.01)
    assert row["duration_minutes"] > 0 and row["estimated_energy_kwh"] > 0


def test_nothing_is_generated_before_the_ride_confirms(database):
    confirmed(database, approve=False)
    assert booking_trips() == []
    assert earnings() == []


def test_the_driver_id_carries_no_name_or_number(database):
    confirmed(database)
    row = booking_trips()[0]
    with db.conn() as c:
        alex = c.execute("select name, phone from users where id = 1").fetchone()
    assert row["driver_id"].startswith("BK-") and len(row["driver_id"]) == 7
    assert alex["name"].lower() not in row["driver_id"].lower()
    assert (alex["phone"] or "").replace("+", "") not in row["driver_id"]
    with db.conn() as c:
        events = c.execute("select driver_id, detail from buyer_events where trip_id = %s",
                           (row["id"],)).fetchall()
    for event in events:
        assert event["driver_id"] == row["driver_id"]
        assert alex["name"] not in event["detail"]


def test_generation_is_deterministic_from_the_match_id(database):
    first = telemetry._generate({"id": 7}, 12.5)
    second = telemetry._generate({"id": 7}, 12.5)
    other = telemetry._generate({"id": 8}, 12.5)
    assert first == second, "the same match must always produce the same trip"
    assert first != other
    assert telemetry.anonymous_driver(1) == telemetry.anonymous_driver(1)
    assert telemetry.anonymous_driver(1) != telemetry.anonymous_driver(2)


def test_generated_events_use_the_same_thresholds_as_the_fixture(database):
    confirmed(database)
    with db.conn() as c:
        events = c.execute("select * from buyer_events where trip_id like 'BK-%'").fetchall()
    allowed = {kind: threshold for kind, threshold, _ in telemetry.RULES}
    for event in events:
        assert event["threshold"] == allowed[event["type"]]
        assert event["value"] > event["threshold"], "a flagged event must be over its threshold"
        expected = "Review" if event["value"] >= event["threshold"] + 0.10 else "Watch"
        assert event["severity"] == expected
        assert "simulated" in event["detail"]


# ---------------------------------------------------------------- dedupe

def test_repeated_approval_does_not_insert_a_second_trip(database):
    match = confirmed(database)
    for _ in range(3):
        apply.approve_booking(match["booking"]["id"])
    assert len(booking_trips()) == 1
    assert len(earnings()) == 1


def test_repeated_accepts_do_not_insert_a_second_trip(database):
    match = confirmed(database)
    for _ in range(3):
        for user_id in (1, 2, 3):
            apply.accept(match["id"], user_id)
    assert len(booking_trips()) == 1


def test_a_replan_after_confirmation_does_not_insert_a_second_trip(database):
    match = confirmed(database)
    apply.run_planning("test", match["driver_trip_id"])     # confirmed groups are left alone
    assert len(booking_trips()) == 1
    assert len(earnings()) == 1


def test_calling_the_recorder_directly_twice_is_safe(database):
    match = confirmed(database)
    with db.conn() as c:
        first = telemetry.record_confirmed_ride(c, match["id"])
        second = telemetry.record_confirmed_ride(c, match["id"])
    assert first == second == f"BK-{match['id']:04d}"
    assert len(booking_trips()) == 1


# ---------------------------------------------------------------- scoring

def test_the_generated_trip_is_scored_by_the_committed_models(database):
    confirmed(database)
    row = booking_trips()[0]
    with db.conn() as c:
        score = c.execute("select * from buyer_trip_scores where trip_id = %s", (row["id"],)).fetchone()
    assert score["scored_by"] == "runtime"
    assert 0.0 <= score["risk_probability"] <= 1.0
    assert score["predicted_kwh_per_mi"] > 0 and score["actual_kwh_per_mi"] > 0
    assert score["features"]["miles"] == pytest.approx(row["miles"], abs=0.01)
    # The risk model must not have been handed an event count.
    assert set(bm.RISK_FEATURES) <= set(score["features"])


def test_scoring_survives_a_missing_anomaly_model(database, monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "FOREST_FILE", tmp_path / "gone.joblib")
    bm.reset_forest_cache()
    try:
        match = confirmed(database)
        assert match["status"] == "confirmed", "a missing model must not block a confirmation"
        with db.conn() as c:
            score = c.execute("select * from buyer_trip_scores where trip_id like 'BK-%'").fetchone()
        assert score["anomaly_score"] is None and score["anomaly_flagged"] is None
        assert score["risk_probability"] is not None, "the committed parameters still score"
        assert score["scored_by"] == "runtime"
    finally:
        bm.reset_forest_cache()


def test_a_trip_with_no_usable_model_at_all_is_marked_unscored(database, monkeypatch, tmp_path):
    """Nothing to score with: no committed parameters and no anomaly model on disk."""
    match = confirmed(database)
    monkeypatch.setattr(bm, "FOREST_FILE", tmp_path / "gone.joblib")
    bm.reset_forest_cache()
    try:
        with db.conn() as c:
            c.execute("delete from buyer_trips where source = 'booking'")
            c.execute("delete from buyer_model_runs")
            trip_id = telemetry.record_confirmed_ride(c, match["id"])
            score = c.execute("select * from buyer_trip_scores where trip_id = %s",
                              (trip_id,)).fetchone()
        assert score["scored_by"] == "unscored"
        assert score["risk_probability"] is None and score["predicted_kwh_per_mi"] is None
        assert score["anomaly_score"] is None
        # The trip itself is still recorded, so the booking link is not lost.
        assert score["actual_kwh_per_mi"] > 0
    finally:
        bm.reset_forest_cache()


def test_only_the_anomaly_model_still_counts_as_scored(database, monkeypatch):
    """The parametric models are gone but the forest is present, so the trip is partly scored."""
    # Model binaries are intentionally not committed; provide the available-model
    # result explicitly so this classification test also works in a fresh checkout.
    monkeypatch.setattr(bm, "anomaly_score", lambda features: (-0.6, True))
    match = confirmed(database)
    with db.conn() as c:
        c.execute("delete from buyer_trips where source = 'booking'")
        c.execute("delete from buyer_model_runs")
        trip_id = telemetry.record_confirmed_ride(c, match["id"])
        score = c.execute("select * from buyer_trip_scores where trip_id = %s", (trip_id,)).fetchone()
    assert score["scored_by"] == "runtime"
    assert score["anomaly_score"] == pytest.approx(-0.6)
    assert score["anomaly_flagged"] is True
    assert score["risk_probability"] is None and score["predicted_kwh_per_mi"] is None


def test_a_telemetry_fault_never_blocks_the_ride(database, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("telemetry on fire")
    monkeypatch.setattr(telemetry, "_write", explode)
    match = confirmed(database)
    assert match["status"] == "confirmed"
    assert booking_trips() == []


# ---------------------------------------------------------------- cancelling

def test_cancelling_the_driver_voids_the_trip_rather_than_deleting_it(database):
    match = confirmed(database)
    apply.cancel_trip(match["driver_trip_id"])
    assert booking_trips() == [], "a voided trip leaves the active dataset"
    kept = booking_trips(include_voided=True)
    assert len(kept) == 1 and kept[0]["voided"] is True
    assert earnings() == [], "the payout goes with it"


def test_a_voided_trip_disappears_from_the_portal_but_is_still_counted(database):
    match = confirmed(database)
    before = apply.buyer_dataset()["datasetSummary"]["tripCount"]
    apply.cancel_trip(match["driver_trip_id"])
    after = apply.buyer_dataset()
    assert after["datasetSummary"]["tripCount"] == before - 1
    assert not [t for t in after["demoTrips"] if t["id"].startswith("BK-")]
    insights = apply.buyer_insights()
    assert insights["liveBookingTrips"] == 0 and insights["voidedBookingTrips"] == 1


# ---------------------------------------------------------------- owner earnings

def test_the_owner_earns_the_configured_demo_amount(database):
    match = confirmed(database)
    rows = earnings()
    assert len(rows) == 1
    assert rows[0]["owner_id"] == 4 and rows[0]["match_id"] == match["id"]
    assert rows[0]["amount_cents"] == config.DEMO_DATA_PAYOUT_CENTS
    assert rows[0]["simulated"] is True
    assert rows[0]["buyer_trip_id"] == f"BK-{match['id']:04d}"


def test_the_payout_amount_comes_from_config(database, monkeypatch):
    monkeypatch.setattr(config, "DEMO_DATA_PAYOUT_CENTS", 250)
    confirmed(database)
    assert earnings()[0]["amount_cents"] == 250


def test_the_default_payout_is_85_cents():
    from pathlib import Path
    source = Path(config.__file__).read_text(encoding="utf-8")
    assert 'os.getenv("DEMO_DATA_PAYOUT_CENTS", "85")' in source


def test_the_owner_dashboard_shows_the_earnings_labelled_as_demo(database):
    confirmed(database)
    demo_accounts.create()
    with TestClient(app) as sam:
        sam.post("/auth/login", json={"email": "sam@eride.demo", "password": "demo-sam-2026"})
        board = sam.get("/me/dashboard").json()
    money = board["data_earnings"]
    assert money["trips"] == 1 and money["cents"] == config.DEMO_DATA_PAYOUT_CENTS
    assert money["simulated"] is True
    assert "no money moves" in money["basis"].lower()
    assert money["per_trip_cents"] == config.DEMO_DATA_PAYOUT_CENTS


def test_a_rider_sees_no_earnings(database):
    confirmed(database)
    demo_accounts.create()
    with TestClient(app) as alex:
        alex.post("/auth/login", json={"email": "alex@eride.demo", "password": "demo-alex-2026"})
        board = alex.get("/me/dashboard").json()
    assert board["data_earnings"]["trips"] == 0 and board["data_earnings"]["cents"] == 0


# ---------------------------------------------------------------- the portal and a reset

def test_the_portal_shows_the_live_booking_trip(database):
    match = confirmed(database)
    dataset = apply.buyer_dataset()
    assert dataset["datasetSummary"]["tripCount"] == 49
    live = [t for t in dataset["demoTrips"] if t["id"] == f"BK-{match['id']:04d}"]
    assert len(live) == 1
    insights = apply.buyer_insights()
    assert insights["liveBookingTrips"] == 1
    scored = next(t for t in insights["tripScores"] if t["tripId"] == live[0]["id"])
    assert scored["source"] == "booking" and scored["matchId"] == match["id"]
    assert scored["scoredBy"] == "runtime"


def test_a_reset_clears_generated_trips_and_earnings(database):
    confirmed(database)
    assert len(booking_trips()) == 1 and len(earnings()) == 1
    seed.reset()
    assert booking_trips(include_voided=True) == []
    assert earnings() == []
    # The fixture trips and their scores come back untouched.
    with db.conn() as c:
        assert c.execute("select count(*) as n from buyer_trips").fetchone()["n"] == 48
        assert c.execute("select count(*) as n from buyer_trip_scores").fetchone()["n"] == 48
