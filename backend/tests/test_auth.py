"""Account sessions and authorization exercised against isolated PostgreSQL."""
import hashlib
import json
from fastapi.testclient import TestClient
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import apply, config, db
from app.main import app
from test_database import database, postgres, trip
from scripts.grant_buyer import grant
from scripts.load_buyer_dataset import FIXTURE


PASSWORD = " spaces stay here "


def signup(client, email="rider@example.com", role="rider", name="Rider"):
    return client.post("/auth/signup", json={"name": name, "email": email, "password": PASSWORD, "role": role})


def test_signup_login_logout_and_revoked_session(database):
    with TestClient(app) as client:
        assert client.get("/auth/me").json() == {"user": None}
        response = signup(client, " RIDER@Example.com ")
        assert response.status_code == 201
        user = response.json()["user"]
        assert user["email"] == "rider@example.com" and user["role"] == "rider"
        assert set(user) == {"id", "name", "email", "role"}
        cookie = client.cookies.get("eride_session")
        assert cookie and "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        with db.conn() as c:
            password_hash = c.execute("select password_hash from auth_accounts where user_id = %s", (user["id"],)).fetchone()["password_hash"]
            token_hash = c.execute("select token_hash from auth_sessions where user_id = %s", (user["id"],)).fetchone()["token_hash"]
        assert PASSWORD not in password_hash and password_hash.startswith("scrypt$131072$8$1$")
        assert token_hash == hashlib.sha256(cookie.encode()).hexdigest()
        assert client.get("/auth/me").json()["user"] == user
        assert client.get("/me/dashboard").json()["user"]["id"] == user["id"]
        assert client.get("/me/dashboard").headers["cache-control"] == "no-store"
        assert signup(client).status_code == 409
        assert client.post("/auth/logout").status_code in (200, 204)
        client.cookies.set("eride_session", cookie, domain="testserver.local", path="/")
        assert client.get("/auth/me").json() == {"user": None}
        assert client.get("/me/dashboard").status_code == 401
        assert client.post("/auth/login", json={"email": "rider@example.com", "password": PASSWORD.strip()}).status_code == 401
        login = client.post("/auth/login", json={"email": "RIDER@example.com", "password": PASSWORD})
        assert login.status_code == 200 and login.json()["user"] == user
        assert client.cookies.get("eride_session") != cookie
        with db.conn() as c:
            c.execute("update auth_sessions set expires_at = now() - interval '1 minute'")
        assert client.get("/auth/me").json() == {"user": None}


def test_validation_roles_csrf_and_admin_fail_closed(database, monkeypatch):
    monkeypatch.setattr(config, "API_SERVICE_TOKEN", "")
    with TestClient(app) as client:
        assert signup(client, role="buyer").status_code == 422
        assert signup(client, "bad-address").status_code == 422
        assert client.post("/auth/signup", json={"name": "Rider", "email": "x@example.com", "role": "rider", "password": "short"}).status_code == 422
        assert client.post("/auth/signup", json={"name": "Rider", "email": "x@example.com", "role": "rider", "password": PASSWORD}, headers={"Origin": "https://attacker.example"}).status_code == 403
        for method, path in [("post", "/demo/bootstrap"), ("post", "/demo/trips"), ("post", "/demo/restart"), ("get", "/events"), ("get", "/agent-runs"), ("get", "/ready")]:
            assert getattr(client, method)(path).status_code == 401
        assert client.post("/planner/run", json={}).status_code == 401
        assert client.get("/health").status_code == 200
        user = signup(client).json()["user"]
        assert client.get("/buyer/dataset").status_code == 403
        assert client.post("/auth/logout", headers={"Origin": "https://attacker.example"}).status_code == 403
        assert client.get("/auth/me").json()["user"] == user
        assert client.post("/demo/restart").status_code == 403


def test_users_cannot_read_or_mutate_other_accounts(database, monkeypatch):
    monkeypatch.setattr(config, "API_SERVICE_TOKEN", "trusted-test-token")
    with TestClient(app) as rider, TestClient(app) as other, TestClient(app) as owner:
        first = signup(rider).json()["user"]
        second = signup(other, "other@example.com").json()["user"]
        landlord = signup(owner, "owner@example.com", "owner", "Owner").json()["user"]
        own_trip = trip(database, first["id"])
        foreign_trip = trip(database, second["id"])
        assert rider.get(f"/users/{second['id']}/dashboard").status_code == 403
        assert rider.get(f"/trips/{foreign_trip['id']}/matches").status_code == 403
        assert rider.post(f"/trips/{foreign_trip['id']}/cancel").status_code == 403
        assert rider.patch(f"/trips/{foreign_trip['id']}", json={"dest_name": "Wrong"}).status_code == 403
        assert rider.post(f"/trips/{foreign_trip['id']}/plan").status_code == 403
        forged = {"user_id": second["id"], "role": "passenger", **database["destination"], "window_start": database["window_start"].isoformat(), "window_end": database["window_end"].isoformat()}
        assert rider.post("/trips", json=forged).status_code == 403
        assert rider.get(f"/users/{second['id']}/dashboard", headers={"Authorization": "Bearer trusted-test-token"}).status_code == 403
        assert rider.get(f"/trips/{own_trip['id']}/matches").status_code == 200
        assert rider.post("/vehicles/1/cancel").status_code == 403
        assert owner.post("/vehicles/1/cancel").status_code == 403
        assert owner.get("/vehicles?owner_id=4").status_code == 403
        assert owner.get("/vehicles").json() == []
        assert landlord["role"] == "owner"


def test_match_participant_owner_and_driver_permissions(database):
    with TestClient(app) as driver, TestClient(app) as passenger, TestClient(app) as owner, TestClient(app) as stranger:
        d = signup(driver, "driver@example.com").json()["user"]
        p = signup(passenger, "passenger@example.com").json()["user"]
        o = signup(owner, "owner@example.com", "owner").json()["user"]
        signup(stranger, "stranger@example.com")
        with db.conn() as c:
            c.execute("update vehicles set owner_id = %s where id = 1", (o["id"],))
        pt = trip(database, p["id"], "passenger")
        dt = trip(database, d["id"])
        plan = apply.run_planning("auth_test", dt["id"])
        mid = plan["match_ids"][0]
        match = apply.get_match(mid)
        bid = match["booking"]["id"]
        assert driver.get(f"/matches/{mid}").status_code == 200
        assert passenger.get(f"/matches/{mid}").status_code == 200
        assert owner.get(f"/matches/{mid}").status_code == 200
        assert stranger.get(f"/matches/{mid}").status_code == 403
        assert passenger.post(f"/matches/{mid}/vehicle", json={"vehicle_id": 2}).status_code == 403
        assert driver.post(f"/matches/{mid}/accept", json={"user_id": p["id"]}).status_code == 403
        assert driver.post(f"/matches/{mid}/accept", json={}).status_code == 200
        assert passenger.post(f"/matches/{mid}/accept", json={}).status_code == 200
        assert driver.post(f"/bookings/{bid}/approve").status_code == 403
        assert stranger.post(f"/bookings/{bid}/decline").status_code == 403
        assert owner.post(f"/bookings/{bid}/approve").json()["match"]["status"] == "confirmed"


def test_login_throttled_and_buyer_requires_grant(database):
    with TestClient(app) as client:
        user = signup(client).json()["user"]
        grant("RIDER@example.com")
        assert client.get("/auth/me").json() == {"user": None}
        assert client.post("/auth/login", json={"email": "rider@example.com", "password": PASSWORD}).status_code == 200
        assert client.get("/auth/me").json()["user"]["role"] == "buyer"
        dataset = client.get("/buyer/dataset")
        assert dataset.status_code == 200
        assert dataset.json() == json.loads(FIXTURE.read_text(encoding="utf-8"))   # served from buyer_* tables
        assert dataset.headers["cache-control"] == "no-store"
        assert client.post("/trips", json={"role": "passenger", **database["destination"], "window_start": database["window_start"].isoformat(), "window_end": database["window_end"].isoformat()}).status_code == 403
        client.post("/auth/logout")
        statuses = [client.post("/auth/login", json={"email": "rider@example.com", "password": "wrong password"}).status_code for _ in range(10)]
        assert statuses[0] == 401 and statuses[-1] == 429


def test_owner_creates_only_own_vehicle_and_rider_books_actual_destination(database):
    with TestClient(app) as owner, TestClient(app) as rider:
        landlord = signup(owner, "owner@example.com", "owner").json()["user"]
        traveler = signup(rider).json()["user"]
        vehicle = {"make_model": "Account car", "fuel_type": "ev", "seats": 5, "range_mi": 240, "efficiency": 0.27,
                   "price_per_hour_cents": 700, "avail_start": database["window_start"].isoformat(),
                   "avail_end": database["window_end"].isoformat()}
        assert rider.post("/vehicles", json=vehicle).status_code == 403
        assert owner.post("/vehicles", json={**vehicle, "owner_id": traveler["id"]}).status_code == 403
        created = owner.post("/vehicles", json=vehicle)
        assert created.status_code == 200 and created.json()["owner_id"] == landlord["id"]
        assert len(owner.get("/me/dashboard").json()["vehicles"]) == 1
        trip_body = {"role": "passenger", "dest_name": "Library", "origin_lat": 42.28, "origin_lng": -83.74,
                     "dest_lat": 42.3, "dest_lng": -83.75, "window_start": database["window_start"].isoformat(),
                     "window_end": database["window_end"].isoformat()}
        result = rider.post("/trips", json=trip_body)
        assert result.status_code == 200
        row = result.json()["trip"]
        assert row["user_id"] == traveler["id"] and row["dest_name"] == "Library"
        assert row["dest_lat"] == 42.3
        retried = rider.post(f"/trips/{row['id']}/plan")
        assert retried.status_code == 200 and set(retried.json()) == {"matches"}


@pytest.mark.parametrize("peer,trusted", [("127.0.0.1", True), ("203.0.113.20", False)])
def test_proxy_client_quota_and_untrusted_forwarded_headers(database, peer, trusted):
    # Same middleware and explicit trust boundary as the documented Uvicorn flags.
    proxied = ProxyHeadersMiddleware(app, trusted_hosts=["127.0.0.1", "::1"])
    with TestClient(proxied, client=(peer, 49152)) as client:
        statuses = []
        for index in range(31):
            # Trusted edge supplies one real address. An untrusted caller rotates
            # forged headers but must still consume its actual peer's quota.
            forwarded = "198.51.100.10" if trusted else f"198.51.100.{index + 1}"
            result = client.post("/auth/login", json={"email": f"attempt-{index}@example.com", "password": PASSWORD},
                                 headers={"X-Forwarded-For": forwarded, "X-Real-IP": forwarded})
            statuses.append(result.status_code)
        assert statuses[:30] == [401] * 30
        assert statuses[30] == 429
        next_client = client.post("/auth/login", json={"email": "new-client@example.com", "password": PASSWORD},
                                  headers={"X-Forwarded-For": "198.51.100.200"})
        assert next_client.status_code == (401 if trusted else 429)
