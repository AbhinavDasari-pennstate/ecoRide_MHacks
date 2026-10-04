"""Failure behavior at the voice provider boundary."""
import asyncio
import json

import httpx
import pytest
from mcp import Client

from app import apply, config, notify, voice


def failing_client(seen, message):
    def fail(request):
        seen.append(request)
        raise httpx.ReadTimeout(message, request=request)

    return httpx.Client(transport=httpx.MockTransport(fail))


def call(tool, **args):
    async def go():
        async with Client(voice.mcp) as client:
            result = await client.call_tool(tool, args)
            return json.loads(result.content[0].text)

    return asyncio.run(go())


def test_send_sms_reports_uncertain_network_failure_without_retry_or_details(monkeypatch):
    for key, value in {
        "TWILIO_ACCOUNT_SID": "ACtest",
        "TWILIO_AUTH_TOKEN": "secret-token",
        "TWILIO_PHONE_NUMBER": "+17345550199",
        "TWILIO_SMS_TEMPLATE": "",
    }.items():
        monkeypatch.setattr(config, key, value)
    seen = []
    monkeypatch.setattr(voice, "_http", failing_client(seen, "secret-token leaked upstream"))

    with pytest.raises(ValueError, match="text status is uncertain.*check delivery") as error:
        voice.send_sms("+17345550102", "hello")

    assert len(seen) == 1
    assert "secret-token" not in str(error.value)


def test_call_user_reports_uncertain_network_failure_without_retry_or_details(monkeypatch):
    for key, value in {
        "ELEVENLABS_API_KEY": "secret-key",
        "ELEVENLABS_AGENT_ID": "ag1",
        "ELEVENLABS_PHONE_NUMBER_ID": "pn1",
    }.items():
        monkeypatch.setattr(config, key, value)
    monkeypatch.setattr(apply, "user_rides", lambda user_id: {
        "user": {"id": user_id, "name": "Maya", "phone": "+17345550102"},
        "rides": [],
    })
    monkeypatch.setattr(notify, "call_guard", lambda user_id: None)
    monkeypatch.setattr(notify, "record_outbound_call", lambda user_id, reason: None)
    seen = []
    monkeypatch.setattr(voice, "_http", failing_client(seen, "secret-key leaked upstream"))

    with pytest.raises(ValueError, match="call status is uncertain.*check before") as error:
        voice.call_user(2, "confirm your seat")

    assert len(seen) == 1
    assert "secret-key" not in str(error.value)


def test_request_ride_without_match_asks_caller_to_check_rides(monkeypatch):
    monkeypatch.setattr(apply, "create_trip", lambda data: {"id": 3, "dest_name": "Meijer"})
    monkeypatch.setattr(apply, "run_planning", lambda *args, **kwargs: {})
    monkeypatch.setattr(apply, "matches_for_trip", lambda trip_id: [])
    monkeypatch.setattr(apply, "find_duplicate_trip", lambda *args, **kwargs: None)

    out = call("request_ride", user_id=2, destination="Meijer", earliest="2026-10-10T13:45")

    assert "check your rides later" in out["say"].lower()
    assert "we'll let you know" not in out["say"].lower()
