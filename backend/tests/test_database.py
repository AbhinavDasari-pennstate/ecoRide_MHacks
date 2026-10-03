"""Integration checks against isolated, real PostgreSQL; never use configured Neon credentials."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

import pgserver
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import apply, config, db, maps
from app.main import app
from scripts import seed


@pytest.fixture(scope="module")
def postgres(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("database") / "pgdata")
    yield server.get_uri()
    db.close_pool()
    server.cleanup()


@pytest.fixture
def database(postgres, monkeypatch):
    db.close_pool()
    monkeypatch.setattr(db, "_url", lambda direct=False: postgres)
    monkeypatch.setattr(config, "DATABASE_URL", "local")
    monkeypatch.setattr(config, "MAPS_SERVER_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "API_SERVICE_TOKEN", "")
    monkeypatch.setattr(config, "PLANNER", "deterministic")
    monkeypatch.setattr(config, "EXPLAIN", "template")
    maps._dist_mem.clear()
    maps._route_mem.clear()
    s = seed.reset(clear_cache=True)
    yield s
    db.close_pool()


def trip(s, user=1, role="driver"):
    return apply.create_trip({"user_id": user, "role": role, **s["destination"],
                              "window_start": s["window_start"], "window_end": s["window_end"]})


def match(c, tid, start):
    return c.execute("insert into matches(driver_trip_id, vehicle_id, depart_time) values (%s, 1, %s) returning id",
                     (tid, start)).fetchone()["id"]


def book(c, mid, start, end, status="requested"):
    c.execute("insert into bookings(match_id, vehicle_id, start_ts, end_ts, hours, price_cents, status)"
              " values (%s, 1, %s, %s, 1, 800, %s)", (mid, start, end, status))


def test_migrate_twice_preserves_rows_and_detects_changed_migration(database, monkeypatch, tmp_path):
    t = trip(database)
    assert db.apply_schema() == []
    with db.conn() as c:
        assert c.execute("select id from trips").fetchone()["id"] == t["id"]
    original = next(db.MIGRATIONS.glob("*.sql"))
    (tmp_path / original.name).write_text(original.read_text() + "\n-- edited\n")
    monkeypatch.setattr(db, "MIGRATIONS", tmp_path)
    with pytest.raises(ValueError, match="Applied migration changed"):
        db.apply_schema()


def test_overlap_rolls_back_booking_and_event(database):
    t = trip(database)
    start = database["window_start"]
    with pytest.raises(psycopg.errors.ExclusionViolation):
        with db.conn() as c:
            book(c, match(c, t["id"], start), start, start + timedelta(hours=1))
            book(c, match(c, t["id"], start), start, start + timedelta(hours=1))
            db.event(c, "must_rollback", {})
    with db.conn() as c:
        assert c.execute("select count(*) as n from bookings").fetchone()["n"] == 0
        assert c.execute("select count(*) as n from events where kind = 'must_rollback'").fetchone()["n"] == 0


def test_adjacent_and_cancelled_bookings_are_allowed(database):
    t = trip(database)
    start = database["window_start"]
    with db.conn() as c:
        for offset, status in [(0, "requested"), (1, "approved"), (0, "cancelled")]:
            a = start + timedelta(hours=offset)
            book(c, match(c, t["id"], a), a, a + timedelta(hours=1), status)


def test_concurrent_reservations_only_one_commits(database):
    t = trip(database)
    start = database["window_start"]
    with db.conn() as c:
        mids = [match(c, t["id"], start) for _ in range(2)]
    barrier = threading.Barrier(2, timeout=10)

    def reserve(mid):
        try:
            with db.conn() as c:
                c.execute("set local statement_timeout = '10s'")
                book(c, mid, start, start + timedelta(hours=1))
                barrier.wait()
            return True
        except (psycopg.errors.ExclusionViolation, psycopg.errors.DeadlockDetected):
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reserve, mids)) == [False, True]
    with db.conn() as c:
        assert c.execute("select count(*) as n from bookings").fetchone()["n"] == 1


def test_one_live_membership_and_atomic_transfer(database):
    t = trip(database)
    with db.conn() as c:
        first, second = [match(c, t["id"], database["window_start"]) for _ in range(2)]
        c.execute("insert into match_members(match_id, trip_id) values (%s, %s)", (first, t["id"]))
    with pytest.raises(psycopg.errors.ExclusionViolation):
        with db.conn() as c:
            c.execute("insert into match_members(match_id, trip_id) values (%s, %s)", (second, t["id"]))
    with db.conn() as c:
        c.execute("insert into match_members(match_id, trip_id) values (%s, %s)", (second, t["id"]))
        c.execute("update match_members set status = 'cancelled' where match_id = %s", (first,))


@pytest.mark.parametrize("field,value", [("efficiency", 0), ("efficiency", float("nan")),
    ("range_mi", float("inf")), ("lat", 100)])
def test_invalid_vehicle_data_rejected_by_postgres(database, field, value):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.conn() as c:
            c.execute(f"update vehicles set {field} = %s where id = 1", (value,))


def test_identity_idempotency_linking_and_dashboard(database):
    with TestClient(app) as client:
        body = {"provider": "web", "subject": "student-1", "name": "Alex", "roles": ["driver"],
                "home_lat": 42.28, "home_lng": -83.74}
        first = client.post("/users", json=body)
        assert first.status_code == 200
        uid = first.json()["id"]
        assert client.post("/users", json=body).json()["id"] == uid
        assert client.post("/users", json={**body, "subject": "student-2"}).json()["id"] != uid
        identity = {"provider": "photon", "subject": "verified-demo-phone"}
        assert client.post(f"/users/{uid}/identities", json=identity).status_code == 200
        assert client.post(f"/users/{uid}/identities", json=identity).status_code == 200
        assert client.post("/users/1/identities", json=identity).status_code == 422
        assert client.post("/users", json={**body, **identity}).json()["id"] == uid
        trip(database, uid)
        dashboard = client.get(f"/users/{uid}/dashboard").json()
        assert dashboard["user"]["id"] == uid and len(dashboard["trips"]) == 1
        assert client.get("/users/9999/dashboard").status_code == 404
        assert len(client.get("/vehicles?owner_id=4").json()) == 1
        assert client.get("/ready").json()["database"] == "connected"


def proposed(s):
    trip(s, 2, "passenger")
    trip(s, 3, "passenger")
    d = trip(s)
    result = apply.run_planning("test", d["id"])
    m = apply.get_match(result["match_ids"][0])
    for uid in (1, 2, 3):
        apply.accept(m["id"], uid)
    return apply.approve_booking(m["booking"]["id"])["match"]


def test_replacement_requires_new_owner_approval(database):
    before = proposed(database)
    assert before["status"] == "confirmed"
    apply.cancel_vehicle(before["vehicle_id"])
    after = apply.get_match(before["id"])
    assert after["vehicle_id"] != before["vehicle_id"]
    assert after["booking"]["status"] == "requested" and after["status"] == "proposed"
    assert {m["status"] for m in after["members"]} == {"pending"}
    assert apply.approve_booking(after["booking"]["id"])["match"]["status"] == "proposed"
    for uid in (1, 2, 3):
        after = apply.accept(after["id"], uid)
    assert after["status"] == "confirmed"


def test_failed_replan_keeps_disruption_persisted(database, monkeypatch):
    before = proposed(database)
    original = apply.run_planning
    def fail(*args, **kwargs):
        raise RuntimeError("simulated outage")
    monkeypatch.setattr(apply, "run_planning", fail)
    with pytest.raises(RuntimeError, match="simulated outage"):
        apply.cancel_vehicle(before["vehicle_id"])
    after = apply.get_match(before["id"])
    assert after["status"] == "at_risk" and after["booking"]["status"] == "cancelled"
    assert apply.impact_summary()["matches"] == 0
    monkeypatch.setattr(apply, "run_planning", original)
    with TestClient(app) as client:
        result = client.post("/planner/run", json={"match_id": before["id"], "mode": "deterministic"})
        assert result.status_code == 200
        assert client.get(f"/matches/{before['id']}").json()["status"] == "proposed"


def test_apply_failure_rolls_back_all_match_writes(database, monkeypatch):
    trip(database, 2, "passenger")
    d = trip(database)
    def fail(*args):
        raise RuntimeError("booking write failed")
    monkeypatch.setattr(apply, "_book", fail)
    with pytest.raises(RuntimeError, match="booking write failed"):
        apply.run_planning("test", d["id"])
    with db.conn() as c:
        assert c.execute("select count(*) as n from matches").fetchone()["n"] == 0
        assert c.execute("select count(*) as n from match_members").fetchone()["n"] == 0
        assert c.execute("select count(*) as n from events where kind = 'match_created'").fetchone()["n"] == 0
        assert c.execute("select count(*) as n from events where kind = 'planning_failed'").fetchone()["n"] == 1


def test_service_token_and_pagination(database, monkeypatch):
    monkeypatch.setattr(config, "API_SERVICE_TOKEN", "test-service-secret")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/events").status_code == 401
        client.headers["Authorization"] = "Bearer test-service-secret"
        for query in ("limit=0", "limit=-1", "since=-1", "limit=1001"):
            assert client.get("/events?" + query).status_code == 422
        assert client.get("/events").status_code == 200


def test_remote_seed_requires_explicit_reset_flag(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://unused.invalid/demo")
    with pytest.raises(ValueError, match="--reset-demo-db"):
        seed.reset()


def test_web_demo_bootstrap_is_additive_and_repeatable(database):
    first = apply.demo_bootstrap()
    second = apply.demo_bootstrap()
    assert [u["id"] for u in first["users"]] == [u["id"] for u in second["users"]]
    assert [v["id"] for v in first["vehicles"]] == [v["id"] for v in second["vehicles"]]
    with db.conn() as c:
        assert c.execute("select count(*) as n from users").fetchone()["n"] == 14
        assert c.execute("select count(*) as n from vehicles").fetchone()["n"] == 8
    apply.cancel_vehicle(first["vehicles"][0]["id"])
    assert apply.demo_bootstrap()["vehicles"][0]["active"] is False


def test_web_demo_survives_reload_and_restart_preserves_other_accounts(database):
    other = trip(database)
    # Keep the unrelated request out of the grocery group.
    with db.conn() as c:
        c.execute("update trips set dest_lat = 41 where id = %s", (other["id"],))
    with TestClient(app) as client:
        meta = client.post("/demo/bootstrap").json()
        uid = next(u["id"] for u in meta["users"] if u["alias"] == "alex")
        first = client.post("/demo/trips")
        assert first.status_code == 200
        assert client.post("/demo/trips").json()["trip"]["id"] == first.json()["trip"]["id"]
        dashboard = client.get(f"/users/{uid}/dashboard").json()
        assert len(dashboard["trips"]) == 1
        assert len(dashboard["matches"][0]["members"]) == 3
        assert client.post("/demo/restart").status_code == 200
        assert client.get(f"/users/{uid}/dashboard").json()["trips"][0]["status"] == "cancelled"
    with db.conn() as c:
        assert c.execute("select status from trips where id = %s", (other["id"],)).fetchone()["status"] == "open"


def test_web_vehicle_selection_validates_and_reopens_confirmation(database):
    before = proposed(database)
    with TestClient(app) as client:
        mid = before["id"]
        assert client.post(f"/matches/{mid}/vehicle", json={"vehicle_id": 99999}).status_code == 422
        assert client.get(f"/matches/{mid}").json()["status"] == "confirmed"
        result = client.post(f"/matches/{mid}/vehicle", json={"vehicle_id": 2})
        assert result.status_code == 200
        changed = result.json()
        assert changed["vehicle_id"] == 2 and changed["status"] == "proposed"
        assert changed["booking"]["status"] == "requested"
        assert all(p["status"] == "pending" for p in changed["members"])
