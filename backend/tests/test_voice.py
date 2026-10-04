"""Voice agent tests: Twilio and ElevenLabs request shapes, MCP tools over the in-memory client, the API
token gate, and scripts/setup_voice.py against a fake ElevenLabs/Twilio. No database, no network."""
import asyncio
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app import apply, config, voice

USER = {"id": 2, "name": "Maya", "phone": "+17345550102"}
RIDES = {"user": USER, "rides": [{"trip_id": 1, "match_id": 7, "status": "matched", "summary": "Alex drives Maya to Meijer."}]}


def mock(monkeypatch, module, handler):
    seen = []

    def record(req):
        seen.append(req)
        return handler(req)
    monkeypatch.setattr(module, "_http", httpx.Client(transport=httpx.MockTransport(record)))
    return seen


@pytest.fixture
def twilio(monkeypatch):
    for k, v in {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_PHONE_NUMBER": "+17345550199",
                 "TWILIO_SMS_TEMPLATE": ""}.items():
        monkeypatch.setattr(config, k, v)


def call(tool, **args):
    async def go():
        async with Client(voice.mcp) as c:
            r = await c.call_tool(tool, args)
            return json.loads(r.content[0].text)
    return asyncio.run(go())


# ---------------------------------------------------------------- texts and calls

def test_send_sms_request(monkeypatch, twilio):
    seen = mock(monkeypatch, voice, lambda r: httpx.Response(201, json={"sid": "SM1", "status": "queued"}))
    assert voice.send_sms("+17345550102", "hello") == {"sid": "SM1", "status": "queued"}
    req = seen[0]
    assert str(req.url) == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    assert req.headers["authorization"].startswith("Basic ")
    assert parse_qs(req.content.decode()) == {"From": ["+17345550199"], "To": ["+17345550102"], "Body": ["hello"]}


def test_send_sms_trial_template_and_errors(monkeypatch, twilio):
    monkeypatch.setattr(config, "TWILIO_SMS_TEMPLATE", "sms_appointment_reminders")
    seen = mock(monkeypatch, voice, lambda r: httpx.Response(400, json={"code": 21608, "message": "unverified number"}))
    with pytest.raises(ValueError, match="unverified number.*21608"):
        voice.send_sms("+17345550102", "custom text")
    assert parse_qs(seen[0].content.decode())["Body"] == ["sms_appointment_reminders"]
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "")
    with pytest.raises(ValueError, match="not set up"):
        voice.send_sms("+1", "x")


def test_call_user_request(monkeypatch):
    for k, v in {"ELEVENLABS_API_KEY": "xi", "ELEVENLABS_AGENT_ID": "ag1", "ELEVENLABS_PHONE_NUMBER_ID": "pn1"}.items():
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(apply, "user_rides", lambda uid: RIDES)
    seen = mock(monkeypatch, voice, lambda r: httpx.Response(200, json={"success": True, "conversation_id": "c1"}))
    assert voice.call_user(2, "confirm your seat") == {"calling": "Maya", "conversation_id": "c1"}
    req = seen[0]
    assert str(req.url) == "https://api.elevenlabs.io/v1/convai/twilio/outbound-call" and req.headers["xi-api-key"] == "xi"
    body = json.loads(req.content)
    assert (body["agent_id"], body["agent_phone_number_id"], body["to_number"]) == ("ag1", "pn1", "+17345550102")
    dv = body["conversation_initiation_client_data"]["dynamic_variables"]
    assert dv["user_id"] == "2" and dv["call_reason"] == "confirm your seat" and dv["ride_summary"] == "Alex drives Maya to Meijer."
    assert set(voice.PLACEHOLDERS) <= set(dv)   # every variable the prompt uses gets a value


# ---------------------------------------------------------------- MCP tools

def test_tools_are_listed_with_descriptions():
    async def go():
        async with Client(voice.mcp) as c:
            return (await c.list_tools()).tools
    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == {"find_caller", "request_ride", "my_rides", "accept_ride", "approve_car", "cancel_ride",
                          "text_ride_details", "call_rider"}
    assert all(t.description for t in tools.values())


def test_find_caller_and_errors(monkeypatch):
    monkeypatch.setattr(apply, "find_user", lambda phone: {"id": 2, "name": "Maya", "roles": ["passenger"]})
    monkeypatch.setattr(apply, "user_rides", lambda uid: RIDES)
    out = call("find_caller", phone="(734) 555-0102")
    assert (out["user_id"], out["name"]) == (2, "Maya") and out["rides"][0]["summary"].startswith("Alex")

    def missing(phone):
        raise LookupError("no user with a phone number ending in 0000")
    monkeypatch.setattr(apply, "find_user", missing)
    assert call("find_caller", phone="000") == {"error": "no user with a phone number ending in 0000"}


def test_request_ride_defaults_and_say(monkeypatch):
    made = {}
    monkeypatch.setattr(apply, "create_trip", lambda d: made.update(d) or {"id": 3, "dest_name": "Meijer"})
    monkeypatch.setattr(apply, "run_planning", lambda *a, **k: {})
    monkeypatch.setattr(apply, "matches_for_trip", lambda tid: [{"id": 1, "summary": "Alex drives Maya and Jordan."}])
    out = call("request_ride", user_id=1, destination="Meijer", earliest="2026-10-10T13:45", role="driver")
    assert out == {"trip_id": 3, "match_id": 1, "say": "Alex drives Maya and Jordan."}
    assert (made["window_end"] - made["window_start"]).total_seconds() == 45 * 60 and made["needs_vehicle"] is None


# ---------------------------------------------------------------- API token gate

def test_token_gate(monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "s3cret")
    monkeypatch.setattr(apply, "events", lambda since, limit: {"events": [], "last_id": 0})
    c = TestClient(app_module().app)
    assert c.get("/health").status_code == 200
    assert c.get("/events").status_code == 401
    assert c.get("/events", headers={"X-Api-Key": "wrong"}).status_code == 401
    assert c.get("/events", headers={"X-Api-Key": "s3cret"}).status_code == 200
    assert c.get("/events", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert c.options("/events", headers={"Origin": "http://x", "Access-Control-Request-Method": "GET"}).status_code == 200


def app_module():
    import app.main
    return app.main


# ---------------------------------------------------------------- setup script against a fake ElevenLabs + Twilio

def test_setup_voice_flow(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("setup_voice", Path(__file__).resolve().parents[1] / "scripts" / "setup_voice.py")
    sv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sv)
    for k, v in {"ELEVENLABS_API_KEY": "xi", "PUBLIC_URL": "https://demo.ngrok.app", "API_TOKEN": "tok123",
                 "ELEVENLABS_AGENT_ID": "", "ELEVENLABS_MCP_SERVER_ID": "", "ELEVENLABS_PHONE_NUMBER_ID": "", "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "twtok",
                 "TWILIO_PHONE_NUMBER": "+17345550199"}.items():
        monkeypatch.setattr(config, k, v)
    env = tmp_path / ".env"
    env.write_text("TWILIO_PHONE_NUMBER=+17345550199\n")
    monkeypatch.setattr(sv, "ENV", env)
    monkeypatch.setattr(sv, "check_public_url", lambda url: None)

    def fake(req):
        path, method = req.url.path, req.method
        if req.url.host == "api.twilio.com":
            return httpx.Response(200, json={"incoming_phone_numbers": [{"phone_number": "+17345550199"}]})
        routes = {("POST", "/v1/convai/mcp-servers"): {"id": "mcp2"},
                  ("GET", "/v1/convai/agents"): {"agents": []},
                  ("POST", "/v1/convai/agents/create"): {"agent_id": "ag9"},
                  ("GET", "/v1/convai/phone-numbers"): [],
                  ("POST", "/v1/convai/phone-numbers"): {"phone_number_id": "pn9"},
                  ("PATCH", "/v1/convai/phone-numbers/pn9"): {}}
        return httpx.Response(200, json=routes[(method, path)])
    seen = mock(monkeypatch, sv, fake)
    sv.main([])

    body = {(r.method, r.url.path): json.loads(r.content) if r.content else None for r in seen}
    mcp_cfg = body[("POST", "/v1/convai/mcp-servers")]["config"]
    assert mcp_cfg["url"] == "https://demo.ngrok.app/mcp" and mcp_cfg["transport"] == "STREAMABLE_HTTP"
    assert mcp_cfg["request_headers"] == {"X-Api-Key": "tok123"}
    agent = body[("POST", "/v1/convai/agents/create")]["conversation_config"]["agent"]
    assert agent["prompt"]["mcp_server_ids"] == ["mcp2"] and agent["first_message"] == "{{greeting}}"
    assert agent["dynamic_variables"]["dynamic_variable_placeholders"] == voice.PLACEHOLDERS
    assert body[("POST", "/v1/convai/phone-numbers")]["provider"] == "twilio"
    assert body[("PATCH", "/v1/convai/phone-numbers/pn9")] == {"agent_id": "ag9"}
    assert not any(r.method == "DELETE" for r in seen)
    saved = env.read_text()
    assert "ELEVENLABS_AGENT_ID=ag9" in saved and "ELEVENLABS_PHONE_NUMBER_ID=pn9" in saved
    assert "ELEVENLABS_MCP_SERVER_ID=mcp2" in saved
    assert "TWILIO_PHONE_NUMBER=+17345550199" in saved
