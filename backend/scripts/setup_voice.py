"""Wire up the voice agent after local preparation and credential checks.
    python scripts/setup_voice.py --prepare   # local only, before starting the API
    python scripts/setup_voice.py --check     # local only, no secrets printed
    python scripts/setup_voice.py [--browser-only | --buy-number]
Steps: check the tunnel reaches our MCP endpoint -> register it with ElevenLabs -> create or update the
"ecoRide" agent -> import the Twilio number into ElevenLabs and put the agent on it.
Needs in .env: ELEVENLABS_API_KEY, PUBLIC_URL (https tunnel to the running API). For phone calls also
TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN, plus TWILIO_PHONE_NUMBER (or --buy-number buys a 734 number on a
paid account). Writes API_TOKEN, ELEVENLABS_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID, TWILIO_PHONE_NUMBER to .env."""
import argparse
import asyncio
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import dotenv_values, set_key  # noqa: E402

from app import config, voice  # noqa: E402

ENV = Path(config.__file__).resolve().parents[1] / ".env"
EL = "https://api.elevenlabs.io/v1/convai"
MCP_NAME = "ecoRide backend"
_http = httpx.Client(timeout=30.0)   # tests swap this for an httpx.MockTransport client


def _redact(text: str) -> str:
    for s in (config.API_TOKEN, config.ELEVENLABS_API_KEY, config.TWILIO_AUTH_TOKEN):
        if s:
            text = text.replace(s, "***")
    return text


def die(msg: str):
    sys.exit("ERROR: " + _redact(msg))


def el(method: str, path: str, *, allow_missing: bool = False, **kw):
    try:
        r = _http.request(method, EL + path, headers={"xi-api-key": config.ELEVENLABS_API_KEY}, **kw)
    except httpx.RequestError:
        die("ElevenLabs connection failed; check its dashboard for any completed changes before rerunning setup")
    if allow_missing and r.status_code == 404:
        return None
    if r.status_code >= 400:
        die(f"ElevenLabs {method} {path} -> {r.status_code}: {r.text[:600]}")
    return r.json() if r.content else {}


def tw(method: str, path: str, **kw):
    sid = config.TWILIO_ACCOUNT_SID
    try:
        r = _http.request(method, f"https://api.twilio.com/2010-04-01/Accounts/{sid}{path}",
                          auth=(sid, config.TWILIO_AUTH_TOKEN), **kw)
    except httpx.RequestError:
        die("Twilio connection failed; check its dashboard for any completed purchase before rerunning setup")
    if r.status_code >= 400:
        die(f"Twilio {method} {path} -> {r.status_code}: {r.text[:400]}")
    return r.json()


def save(key: str, value: str) -> None:
    set_key(ENV, key, value, quote_mode="never")
    setattr(config, key, value)


def prepare() -> None:
    """Add missing example settings without replacing credentials or rotating an existing token."""
    existing = dotenv_values(ENV, interpolate=False)
    example = Path(__file__).resolve().parents[1] / ".env.example"
    ENV.touch(exist_ok=True)
    for key, value in dotenv_values(example, interpolate=False).items():
        if key not in existing:
            set_key(ENV, key, value or "", quote_mode="never")
    save("API_TOKEN", config.API_TOKEN or existing.get("API_TOKEN") or secrets.token_urlsafe(32))
    print("Prepared backend/.env; existing settings preserved. No provider was contacted.")
    print("Fill in the credentials, then start or restart the API so it loads API_TOKEN.")
    print("Run python scripts/setup_voice.py --check to see what is still missing.")


def configuration_errors(browser_only: bool, buy: bool) -> list[str]:
    errors = []
    required = ["API_TOKEN", "PUBLIC_URL", "ELEVENLABS_API_KEY"]
    if not browser_only:
        required += ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]
        if not buy:
            required.append("TWILIO_PHONE_NUMBER")
    for key in required:
        if not getattr(config, key).strip():
            errors.append(f"Missing {key}" + (" (run --prepare before starting the API)" if key == "API_TOKEN" else ""))
    if config.PUBLIC_URL:
        try:
            url = urlsplit(config.PUBLIC_URL)
            valid = url.scheme == "https" and url.hostname and not (url.username or url.password or url.query or url.fragment)
        except ValueError:
            valid = False
        if not valid:
            errors.append("PUBLIC_URL must be an HTTPS tunnel URL without credentials, query parameters or fragments")
    if not browser_only and config.TWILIO_PHONE_NUMBER and not re.fullmatch(r"\+[1-9]\d{7,14}", config.TWILIO_PHONE_NUMBER):
        errors.append("TWILIO_PHONE_NUMBER must use E.164 format, for example +17345550199")
    return errors


def check_public_url(url: str) -> None:
    """List the MCP tools through the tunnel, exactly as ElevenLabs will (catches tunnel, host and token problems)."""
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    try:
        anonymous = _http.post(url, json={})
    except httpx.RequestError:
        die("could not reach the public MCP URL; check the API and tunnel")
    if anonymous.status_code != 401:
        die("public MCP endpoint did not reject an anonymous request; check PUBLIC_URL and restart the API with API_TOKEN")

    async def go():
        async with httpx2.AsyncClient(headers={"X-Api-Key": config.API_TOKEN}, timeout=20) as http:
            async with Client(streamable_http_client(url, http_client=http)) as c:
                return [t.name for t in (await c.list_tools()).tools]
    try:
        names = asyncio.run(go())
    except Exception as e:
        die(f"could not list MCP tools at {url} ({type(e).__name__}: {e}). Is uvicorn running and the tunnel up?")
    print(f"  MCP endpoint OK through the tunnel: {len(names)} tools ({', '.join(names)})")


def _items(data, key: str) -> list:
    return data if isinstance(data, list) else (data or {}).get(key, [])


def register_mcp(url: str) -> str:
    settings = {"approval_policy": "auto_approve_all", "request_headers": {"X-Api-Key": config.API_TOKEN}}
    if config.ELEVENLABS_MCP_SERVER_ID:
        mid = config.ELEVENLABS_MCP_SERVER_ID
        current = (el("GET", f"/mcp-servers/{mid}", allow_missing=True) or {}).get("config", {})
        if current.get("url") == url and current.get("transport") == "STREAMABLE_HTTP":
            el("PATCH", f"/mcp-servers/{mid}", json=settings)
            print(f"  updated MCP server {mid}")
            return mid
    # ElevenLabs cannot PATCH the URL/transport. Leave older registrations intact;
    # another agent may still use them, even if their names happen to match ours.
    new = el("POST", "/mcp-servers", json={"config": {
        "url": url, "name": MCP_NAME, "transport": "STREAMABLE_HTTP", **settings,
        "description": "ecoRide ride tools: find caller, request/accept/cancel rides, texts and calls"}})
    save("ELEVENLABS_MCP_SERVER_ID", new["id"])
    print(f"  registered MCP server {new['id']} -> {url}")
    return new["id"]


def upsert_agent(mcp_id: str) -> str:
    body = {"name": voice.AGENT_NAME, "conversation_config": {
        "agent": {"first_message": voice.FIRST_MESSAGE, "language": "en",
                  "dynamic_variables": {"dynamic_variable_placeholders": voice.PLACEHOLDERS},
                  "prompt": {"prompt": voice.AGENT_PROMPT, "llm": config.ELEVENLABS_LLM, "mcp_server_ids": [mcp_id]}},
        **({"tts": {"voice_id": config.ELEVENLABS_VOICE_ID}} if config.ELEVENLABS_VOICE_ID else {})}}
    agent_id = config.ELEVENLABS_AGENT_ID
    if not agent_id:
        existing = [a["agent_id"] for a in _items(el("GET", "/agents", params={"search": voice.AGENT_NAME}), "agents")
                    if a.get("name") == voice.AGENT_NAME]
        if len(existing) > 1:
            die("multiple ecoRide agents exist; set ELEVENLABS_AGENT_ID to the one you want to update")
        agent_id = existing[0] if existing else ""
    if agent_id:
        el("PATCH", f"/agents/{agent_id}", json=body)
        print(f"  updated agent {agent_id}")
    else:
        agent_id = el("POST", "/agents/create", json=body)["agent_id"]
        print(f"  created agent {agent_id}")
    save("ELEVENLABS_AGENT_ID", agent_id)
    return agent_id


def twilio_number(buy: bool) -> str:
    if config.TWILIO_PHONE_NUMBER:
        return config.TWILIO_PHONE_NUMBER
    if buy:   # a paid account; Twilio bills the number monthly
        found = tw("GET", "/AvailablePhoneNumbers/US/Local.json",
                   params={"AreaCode": "734", "VoiceEnabled": "true", "SmsEnabled": "true"})["available_phone_numbers"]
        if not found:
            die("Twilio has no 734 numbers right now; set TWILIO_PHONE_NUMBER to one you own")
        number = tw("POST", "/IncomingPhoneNumbers.json", data={"PhoneNumber": found[0]["phone_number"]})["phone_number"]
        print(f"  bought {number}")
    else:
        die("set TWILIO_PHONE_NUMBER to the number you want this agent to answer, or use --buy-number")
    save("TWILIO_PHONE_NUMBER", number)
    return number


def attach_number(number: str, agent_id: str) -> str:
    existing = next((p for p in _items(el("GET", "/phone-numbers"), "phone_numbers") if p.get("phone_number") == number), None)
    pid = existing["phone_number_id"] if existing else el("POST", "/phone-numbers", json={
        "phone_number": number, "label": "ecoRide", "provider": "twilio",
        "sid": config.TWILIO_ACCOUNT_SID, "token": config.TWILIO_AUTH_TOKEN})["phone_number_id"]
    el("PATCH", f"/phone-numbers/{pid}", json={"agent_id": agent_id})
    save("ELEVENLABS_PHONE_NUMBER_ID", pid)
    print(f"  {number} is now answered by the agent (ElevenLabs phone number {pid})")
    return pid


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    local = parser.add_mutually_exclusive_group()
    local.add_argument("--prepare", action="store_true", help="Prepare .env and API_TOKEN locally; no network")
    local.add_argument("--check", action="store_true", help="Check local configuration; no network or writes")
    phone = parser.add_mutually_exclusive_group()
    phone.add_argument("--browser-only", action="store_true", help="Set up ElevenLabs browser testing without Twilio")
    phone.add_argument("--buy-number", action="store_true", help="Buy a Twilio 734 number if no number is configured (billed by Twilio)")
    args = parser.parse_args(argv)
    if args.prepare:
        prepare()
        return
    errors = configuration_errors(args.browser_only, args.buy_number)
    if args.check:
        for error in errors:
            print(error)
        if errors:
            raise SystemExit(1)
        print("Configuration ready. Credentials and live calls have not been verified.")
        return
    if errors:
        die("; ".join(errors))
    url = config.PUBLIC_URL + "/mcp"
    print("1/4 checking the tunnel");      check_public_url(url)
    print("2/4 registering MCP server");   mcp_id = register_mcp(url)
    print("3/4 creating the agent");       agent_id = upsert_agent(mcp_id)
    print("4/4 phone number")
    number = ""
    if not args.browser_only:
        number = twilio_number(args.buy_number)
        attach_number(number, agent_id)
    else:
        print("  skipped (--browser-only)")
    print(f"\nDone. Test the agent in your browser: ElevenLabs dashboard -> Agents -> {voice.AGENT_NAME} -> Test.")
    if number:
        print(f"Call {number} from a verified phone, or have the agent call someone: POST /users/{{id}}/call")


if __name__ == "__main__":
    main(sys.argv[1:])
