"""A retried voice tool call, a replan loop or a second button press must not book, text or
call twice. Runs against the same isolated PostgreSQL as test_database.py."""
import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from mcp import Client

from app import apply, config, db, notify, voice
from test_database import database, postgres, trip  # noqa: F401  (pytest fixtures)


def call(tool, **args):
    async def go():
        async with Client(voice.mcp) as c:
            result = await c.call_tool(tool, args)
            return json.loads(result.content[0].text)
    return asyncio.run(go())


def window(s, shift_minutes=0):
    return [(s["window_start"] + timedelta(minutes=shift_minutes)).isoformat(),
            (s["window_end"] + timedelta(minutes=shift_minutes)).isoformat()]


def local_window(s, shift_minutes=0):
    """The window as the voice agent sends it: naive Ann Arbor local time."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(config.TIMEZONE)
    return [(s["window_start"] + timedelta(minutes=shift_minutes)).astimezone(tz).replace(tzinfo=None).isoformat(),
            (s["window_end"] + timedelta(minutes=shift_minutes)).astimezone(tz).replace(tzinfo=None).isoformat()]


# ---------------------------------------------------------------- request_ride

def test_repeated_request_returns_the_same_trip(database):
    earliest, latest = local_window(database)
    first = call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    second = call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    assert first["trip_id"] == second["trip_id"]
    assert first.get("already_booked") is False and second["already_booked"] is True
    assert "already booked" in second["say"].lower()
    with db.conn() as c:
        assert c.execute("select count(*) as n from trips where user_id = 1").fetchone()["n"] == 1


def test_repeat_is_detected_even_when_the_window_only_overlaps(database):
    earliest, latest = local_window(database)
    call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    shifted_earliest, shifted_latest = local_window(database, shift_minutes=20)   # still overlaps
    again = call("request_ride", user_id=1, destination="Meijer",
                 earliest=shifted_earliest, latest=shifted_latest, role="driver")
    assert again["already_booked"] is True
    with db.conn() as c:
        assert c.execute("select count(*) as n from trips where user_id = 1").fetchone()["n"] == 1


def test_a_different_destination_creates_a_new_trip(database, monkeypatch):
    # Only KNOWN_PLACES resolve without a Maps key, so stand in for the geocoder here.
    monkeypatch.setattr(apply.maps, "geocode",
                        lambda query, **kw: {"lat": 42.2750, "lng": -83.7413, "place_id": "union"})
    earliest, latest = local_window(database)
    first = call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    other = call("request_ride", user_id=1, destination="Michigan Union", earliest=earliest, latest=latest,
                 role="driver", needs_car=False)
    assert "error" not in other, other
    assert other["trip_id"] != first["trip_id"] and other["already_booked"] is False


def test_a_cancelled_trip_can_be_rebooked(database):
    earliest, latest = local_window(database)
    first = call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    apply.cancel_trip(first["trip_id"], user_id=1)
    again = call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    assert again["trip_id"] != first["trip_id"] and again["already_booked"] is False


def test_a_request_outside_the_dedupe_window_creates_a_new_trip(database):
    earliest, latest = local_window(database)
    first = call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    with db.conn() as c:   # pretend the first booking happened long before this call
        c.execute("update trips set created_at = now() - interval '2 hours' where id = %s", (first["trip_id"],))
    again = call("request_ride", user_id=1, destination="Meijer", earliest=earliest, latest=latest, role="driver")
    assert again["trip_id"] != first["trip_id"] and again["already_booked"] is False


def test_another_person_booking_the_same_ride_is_not_a_duplicate(database):
    earliest, latest = local_window(database)
    mine = call("request_ride", user_id=2, destination="Meijer", earliest=earliest, latest=latest)
    theirs = call("request_ride", user_id=3, destination="Meijer", earliest=earliest, latest=latest)
    assert mine["trip_id"] != theirs["trip_id"] and theirs["already_booked"] is False


# ---------------------------------------------------------------- texts

@pytest.fixture
def twilio(monkeypatch):
    for key, value in {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "tok",
                       "TWILIO_PHONE_NUMBER": "+17345550199", "TWILIO_SMS_TEMPLATE": ""}.items():
        monkeypatch.setattr(config, key, value)
    sent = []

    def record(request):
        sent.append(request)
        return httpx.Response(201, json={"sid": f"SM{len(sent)}", "status": "queued"})
    monkeypatch.setattr(voice, "_http", httpx.Client(transport=httpx.MockTransport(record)))
    return sent


def matched(database):
    """Alex drives Maya and Jordan; returns the match."""
    for user_id in (2, 3):
        trip(database, user_id, "passenger")
    driver = trip(database, 1)
    return apply.get_match(apply.run_planning("test", driver["id"])["match_ids"][0])


def test_the_same_ride_details_are_texted_once(database, twilio):
    match = matched(database)
    first = call("text_ride_details", user_id=2, match_id=match["id"])
    second = call("text_ride_details", user_id=2, match_id=match["id"])
    assert first["sent"] is True and second["sent"] is False
    assert second["reason"] == "already_sent" and "already texted" in second["say"].lower()
    assert len(twilio) == 1


def test_a_changed_ride_texts_again(database, twilio):
    match = matched(database)
    assert call("text_ride_details", user_id=2, match_id=match["id"])["sent"] is True
    apply.cancel_vehicle(match["vehicle_id"])          # replan: new car, new price, new wording
    assert apply.get_match(match["id"])["summary"] != match["summary"]
    assert call("text_ride_details", user_id=2, match_id=match["id"])["sent"] is True
    assert len(twilio) == 2


def test_two_people_on_one_ride_each_get_their_own_text(database, twilio):
    match = matched(database)
    assert call("text_ride_details", user_id=2, match_id=match["id"])["sent"] is True
    assert call("text_ride_details", user_id=3, match_id=match["id"])["sent"] is True
    assert len(twilio) == 2


def test_the_rest_route_shares_the_same_dedupe(database, twilio):
    from fastapi.testclient import TestClient
    from app.main import app
    match = matched(database)
    with TestClient(app, headers={"Authorization": f"Bearer {config.API_SERVICE_TOKEN}"}) as client:
        first = client.post("/users/2/text", json={"match_id": match["id"]})
        second = client.post("/users/2/text", json={"match_id": match["id"]})
    assert first.json()["sent"] is True and second.json()["sent"] is False
    assert len(twilio) == 1


# ---------------------------------------------------------------- calls

@pytest.fixture
def elevenlabs(monkeypatch):
    for key, value in {"ELEVENLABS_API_KEY": "xi", "ELEVENLABS_AGENT_ID": "ag1",
                       "ELEVENLABS_PHONE_NUMBER_ID": "pn1"}.items():
        monkeypatch.setattr(config, key, value)
    placed = []

    def record(request):
        placed.append(request)
        return httpx.Response(200, json={"success": True, "conversation_id": f"c{len(placed)}"})
    monkeypatch.setattr(voice, "_http", httpx.Client(transport=httpx.MockTransport(record)))
    return placed


def test_the_agent_will_not_ring_the_person_already_on_the_line(database, elevenlabs):
    notify.record_inbound_call(1)                       # Alex's inbound call is in progress
    out = call("call_rider", user_id=1, reason="confirm your seat")
    assert out["placed"] is False and out["reason"] == "already_on_this_call"
    assert "on the line" in out["say"].lower()
    assert placed_none(elevenlabs)


def test_nobody_is_called_twice_within_a_few_minutes(database, elevenlabs):
    first = call("call_rider", user_id=2, reason="confirm your seat")
    assert first.get("conversation_id") == "c1"
    second = call("call_rider", user_id=2, reason="confirm your seat")
    assert second["placed"] is False and second["reason"] == "called_recently"
    assert len(elevenlabs) == 1


def test_a_call_long_enough_ago_is_allowed_again(database, elevenlabs):
    call("call_rider", user_id=2, reason="confirm your seat")
    with db.conn() as c:
        c.execute("update events set ts = now() - interval '30 minutes' where kind = %s", (notify.OUTBOUND_CALL,))
    assert call("call_rider", user_id=2, reason="confirm your seat").get("conversation_id") == "c2"
    assert len(elevenlabs) == 2


def test_the_rest_call_route_shares_the_same_guard(database, elevenlabs):
    from fastapi.testclient import TestClient
    from app.main import app
    notify.record_inbound_call(1)
    with TestClient(app, headers={"Authorization": f"Bearer {config.API_SERVICE_TOKEN}"}) as client:
        out = client.post("/users/1/call", json={"reason": "confirm your seat"}).json()
    assert out["placed"] is False and out["reason"] == "already_on_this_call"
    assert placed_none(elevenlabs)


def placed_none(seen):
    return [r for r in seen if "outbound-call" in str(r.url)] == []


# ---------------------------------------------------------------- the initiation webhook records the caller

def test_the_initiation_webhook_marks_the_caller_as_on_the_line(database, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    with db.conn() as c:
        c.execute("update users set phone = %s where id = 1", ("+19259677432",))
    with TestClient(app, headers={"X-Api-Key": config.API_SERVICE_TOKEN}) as client:
        body = client.post("/voice/initiation", json={"caller_id": "+19259677432"}).json()
    assert body["dynamic_variables"]["user_name"] == "Alex"
    assert notify.call_guard(1)["reason"] == "already_on_this_call"


def test_a_readiness_probe_does_not_count_as_a_call_in_progress(database):
    """preflight.py checks this webhook. It must not then block an outbound test call."""
    from fastapi.testclient import TestClient
    from app.main import app
    with db.conn() as c:
        c.execute("update users set phone = %s where id = 1", ("+19259677432",))
    with TestClient(app, headers={"X-Api-Key": config.API_SERVICE_TOKEN}) as client:
        body = client.post("/voice/initiation", json={"caller_id": "+19259677432", "probe": True}).json()
    assert body["dynamic_variables"]["user_name"] == "Alex"      # the check still proves the path works
    assert notify.call_guard(1) is None
    with db.conn() as c:
        assert c.execute("select count(*) as n from events where kind = %s",
                         (notify.INBOUND_CALL,)).fetchone()["n"] == 0


def test_an_unknown_caller_is_not_recorded_as_anyone(database):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers={"X-Api-Key": config.API_SERVICE_TOKEN}) as client:
        body = client.post("/voice/initiation", json={"caller_id": "+19995550000"}).json()
    assert body["dynamic_variables"] == voice.PLACEHOLDERS
    with db.conn() as c:
        assert c.execute("select count(*) as n from events where kind = %s",
                         (notify.INBOUND_CALL,)).fetchone()["n"] == 0


# ---------------------------------------------------------------- the ledger itself

def test_the_ledger_allows_the_send_when_the_database_is_unreachable(monkeypatch):
    def broken():
        raise RuntimeError("database is down")
    monkeypatch.setattr(db, "conn", broken)
    assert notify.already_sent("sms", "ride_details", 2, "match:1", "abc") is False
    assert notify.call_guard(2) is None
    notify.record_sent("sms", "ride_details", 2, "match:1", "abc")     # must not raise
    notify.record_outbound_call(2, "confirm your seat")
