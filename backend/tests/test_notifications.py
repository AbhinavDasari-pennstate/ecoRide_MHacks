"""Match notices must reach each person once per real change and never storm.

A replan can rewrite the same match many times, and adding a car retries every at_risk match, so
the dedupe key is what stands between the demo and a pile of duplicate texts.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import apply, config, db, notify, voice
from app.main import app
from test_database import database, postgres, trip  # noqa: F401  (pytest fixtures)


@pytest.fixture
def texts(monkeypatch):
    """NOTIFY_ON_MATCH on, Twilio answering, and every outgoing text captured."""
    for key, value in {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "tok",
                       "TWILIO_PHONE_NUMBER": "+17345550199", "TWILIO_SMS_TEMPLATE": ""}.items():
        monkeypatch.setattr(config, key, value)
    monkeypatch.setattr(config, "NOTIFY_ON_MATCH", True)
    monkeypatch.setattr(notify, "_warned_about_template", False)
    sent = []

    def record(request):
        sent.append(request)
        return httpx.Response(201, json={"sid": f"SM{len(sent)}", "status": "queued"})
    monkeypatch.setattr(voice, "_http", httpx.Client(transport=httpx.MockTransport(record)))
    return sent


def matched(database):
    for user_id in (2, 3):
        trip(database, user_id, "passenger")
    driver = trip(database, 1)
    return apply.get_match(apply.run_planning("test", driver["id"])["match_ids"][0])


def notices(user_id=None):
    where = " and payload->>'user_id' = %s" if user_id else ""
    args = [notify.LEDGER] + ([str(user_id)] if user_id else [])
    with db.conn() as c:
        return c.execute("select payload from events where kind = %s and payload->>'channel' = 'match'"
                         f"{where} order by id", args).fetchall()


# ---------------------------------------------------------------- off by default

def test_nothing_is_texted_unless_the_flag_is_on(database, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_ON_MATCH", False)
    calls = []
    monkeypatch.setattr(voice, "send_sms", lambda to, body: calls.append(to))
    matched(database)
    assert calls == []
    # The notice is still recorded, so the app can show it.
    assert [n["payload"]["delivered"] for n in notices()] == ["in_app"] * 4


def test_the_default_configuration_is_off(monkeypatch):
    """Asserts the shipped default, not whatever the developer's .env currently says."""
    from pathlib import Path
    source = Path(config.__file__).read_text(encoding="utf-8")
    assert 'os.getenv("NOTIFY_ON_MATCH", "off")' in source
    for value in ("off", "", "no", "0", "false"):
        assert value.strip().lower() not in ("on", "true", "1", "yes")
    monkeypatch.setattr(config, "NOTIFY_ON_MATCH", False)
    assert notify.texting_on() is False
    monkeypatch.setattr(config, "NOTIFY_ON_MATCH", True)
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"):
        monkeypatch.setattr(config, key, "")
    assert notify.texting_on() is False, "the flag alone must not be enough without Twilio"


# ---------------------------------------------------------------- one notice per person per change

def test_each_person_and_the_owner_are_texted_once_when_a_match_forms(database, texts):
    match = matched(database)
    people = {n["payload"]["user_id"] for n in notices()}
    assert people == {1, 2, 3, 4}                   # Alex, Maya, Jordan and Sam who owns the Tesla
    assert len(texts) == 4
    assert all(n["payload"]["notice"] == "proposed" for n in notices())
    assert all(n["payload"]["delivered"] == "sms" for n in notices())
    assert match["id"]


def test_replanning_the_same_match_does_not_text_again(database, texts):
    match = matched(database)
    assert len(texts) == 4
    for _ in range(3):                             # the shape of a replan loop
        apply.run_planning("test", match["driver_trip_id"])
    assert len(texts) == 4, "a replan that changes nothing must not text anyone"


def test_adding_a_car_cannot_storm_every_match(database, texts):
    matched(database)
    before = len(texts)
    apply.create_vehicle({"owner_id": 5, "make_model": "Spare EV", "fuel_type": "ev", "seats": 5,
                          "range_mi": 240, "efficiency": 0.27, "price_per_hour_cents": 600,
                          "avail_start": database["window_start"], "avail_end": database["window_end"]})
    assert len(texts) == before


def test_confirming_sends_one_more_notice_each(database, texts):
    match = matched(database)
    for user_id in (1, 2, 3):
        apply.accept(match["id"], user_id)
    assert len(texts) == 4, "accepting is not news until the ride is actually confirmed"
    apply.approve_booking(match["booking"]["id"])
    assert apply.get_match(match["id"])["status"] == "confirmed"
    kinds = [n["payload"]["notice"] for n in notices()]
    assert kinds.count("proposed") == 4 and kinds.count("confirmed") == 4
    assert len(texts) == 8
    apply.approve_booking(match["booking"]["id"])   # idempotent approval must not re-announce
    assert len(texts) == 8


def test_a_new_car_announces_the_change_once(database, texts):
    match = matched(database)
    apply.cancel_vehicle(match["vehicle_id"])
    after = apply.get_match(match["id"])
    assert after["vehicle_id"] != match["vehicle_id"]
    changed = [n for n in notices() if n["payload"]["notice"] == "vehicle_changed"]
    assert len(changed) == 4 and "changed" in changed[0]["payload"]["text"]
    apply.run_planning("test", match["driver_trip_id"])
    assert len([n for n in notices() if n["payload"]["notice"] == "vehicle_changed"]) == 4


def test_an_at_risk_match_says_nothing_yet(database, texts):
    match = matched(database)
    before = len(texts)
    with db.conn() as c:     # no car is free, so there is nothing useful to announce
        c.execute("update matches set status = 'at_risk' where id = %s", (match["id"],))
    assert notify.match_state_changed(match["id"]) == []
    assert len(texts) == before


# ---------------------------------------------------------------- trial accounts

def test_a_trial_template_falls_back_to_the_app(database, texts, monkeypatch, caplog):
    monkeypatch.setattr(config, "TWILIO_SMS_TEMPLATE", "sms_appointment_reminders")
    monkeypatch.setattr(notify, "_warned_about_template", False)
    assert notify.texts_carry_details() is False
    matched(database)
    assert texts == [], "a template cannot carry the ride details, so do not send it"
    assert all(n["payload"]["delivered"] == "in_app" for n in notices())
    assert "TWILIO_SMS_TEMPLATE is set" in caplog.text
    assert "ride details" in caplog.text


def test_a_refused_text_still_leaves_the_notice_in_the_app(database, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_ON_MATCH", True)
    for key, value in {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "tok",
                       "TWILIO_PHONE_NUMBER": "+17345550199", "TWILIO_SMS_TEMPLATE": ""}.items():
        monkeypatch.setattr(config, key, value)
    monkeypatch.setattr(voice, "_http", httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(400, json={"code": 21608, "message": "unverified number"}))))
    matched(database)
    assert len(notices()) == 4
    assert all(n["payload"]["delivered"] == "in_app" for n in notices())


# ---------------------------------------------------------------- the in-app feed

def test_the_feed_shows_only_your_own_notices(database, texts):
    from scripts import seed  # noqa: F401
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import demo_accounts
    match = matched(database)
    demo_accounts.create()
    with TestClient(app) as maya:
        maya.post("/auth/login", json={"email": "maya@eride.demo", "password": "demo-maya-2026"})
        mine = maya.get("/me/notifications").json()["notifications"]
    assert mine and all(n["match_id"] == match["id"] for n in mine)
    assert [n["notice"] for n in mine] == ["proposed"]
    assert "Alex drives" in mine[0]["text"] and mine[0]["delivered"] == "sms"
    with TestClient(app) as dana:
        dana.post("/auth/login", json={"email": "buyer@eride.demo", "password": "demo-buyer-2026"})
        assert dana.get("/me/notifications").json()["notifications"] == []


def test_the_feed_needs_a_signed_in_account(database):
    with TestClient(app, headers={"Authorization": f"Bearer {config.API_SERVICE_TOKEN}"}) as client:
        assert client.get("/me/notifications").status_code == 401


def test_a_notice_never_breaks_the_ride(database, monkeypatch):
    """The ride is the product; a notifier fault must not take planning down."""
    monkeypatch.setattr(config, "NOTIFY_ON_MATCH", True)

    def explode(*a, **k):
        raise RuntimeError("provider on fire")
    monkeypatch.setattr(notify, "_audience", explode)
    match = matched(database)
    assert match and match["status"] == "proposed"
