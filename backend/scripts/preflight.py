"""Everything that has to be true before the phone rings, as PASS or FAIL lines.

Read only: it changes no provider settings and places no call, text or email. It prints no keys,
tokens or connection strings, only whether each one is present and working.

    python scripts/preflight.py

Ends with READY TO CALL, or the list of things to fix.
"""
import asyncio
import contextlib
import io
import logging
import os
import sys
from pathlib import Path

for noisy in ("httpx", "httpx2", "mcp", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

from app import config, voice  # noqa: E402

import demo_accounts  # noqa: E402
import seed  # noqa: E402

API = os.getenv("DEMO_API_URL", "http://127.0.0.1:8000").rstrip("/")
FRONTEND = os.getenv("DEMO_FRONTEND_URL", "http://localhost:5173").rstrip("/")
NGROK_AGENT = os.getenv("NGROK_AGENT_URL", "http://127.0.0.1:4040").rstrip("/")
CALLER = os.getenv("DEMO_CALLER", "+19259677432")
EL = "https://api.elevenlabs.io/v1/convai"
TOOLS = 8

failures: list[str] = []
http = httpx.Client(timeout=15.0)


def check(name: str, ok: bool, detail: str = "", fix: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))
    if not ok:
        failures.append(fix or name)
    return ok


def el(path: str):
    try:
        r = http.get(EL + path, headers={"xi-api-key": config.ELEVENLABS_API_KEY})
        return (r.json() if r.status_code < 400 and r.content else None), r.status_code
    except httpx.RequestError:
        return None, 0


def section(title: str) -> None:
    print(f"\n{title}")


# ---------------------------------------------------------------- settings present

def settings() -> None:
    section("settings")
    needed = {"API_TOKEN or API_SERVICE_TOKEN": config.API_TOKEN or config.API_SERVICE_TOKEN,
              "PUBLIC_URL": config.PUBLIC_URL, "ELEVENLABS_API_KEY": config.ELEVENLABS_API_KEY,
              "ELEVENLABS_AGENT_ID": config.ELEVENLABS_AGENT_ID,
              "ELEVENLABS_PHONE_NUMBER_ID": config.ELEVENLABS_PHONE_NUMBER_ID,
              "TWILIO_ACCOUNT_SID": config.TWILIO_ACCOUNT_SID,
              "TWILIO_AUTH_TOKEN": config.TWILIO_AUTH_TOKEN,
              "TWILIO_PHONE_NUMBER": config.TWILIO_PHONE_NUMBER}
    for name, value in needed.items():
        check(f"{name} is set", bool(str(value).strip()), fix=f"fill in {name} in backend/.env")
    check("DEMO_PHONES names the caller", CALLER in seed.DEMO_PHONES.values(),
          f"{', '.join(seed.DEMO_PHONES)}" or "empty",
          f"set DEMO_PHONES=Alex={CALLER} in backend/.env and rerun demo_state.py")
    check("the phone path uses a fast planner", config.VOICE_PLANNER == "deterministic",
          f"VOICE_PLANNER={config.VOICE_PLANNER or '(follows PLANNER)'}",
          "set VOICE_PLANNER=deterministic unless you want Gemini latency on the call")


# ---------------------------------------------------------------- our own processes

def local() -> None:
    section("backend, tunnel and frontend")
    try:
        health = http.get(f"{API}/health").json()
    except Exception:
        health = {}
    check("backend answers /health", bool(health.get("ok")), API,
          f"start the backend: python -m uvicorn app.main:app --port {API.rsplit(':', 1)[-1]}")
    if health:
        check("voice settings loaded", health.get("voice") == "configured", f"voice={health.get('voice')}",
              "restart the backend so it picks up the ELEVENLABS_* ids")
        check("texting settings loaded", health.get("sms") == "configured", f"sms={health.get('sms')}",
              "restart the backend so it picks up the TWILIO_* settings")

    public = ""
    try:
        tunnels = http.get(f"{NGROK_AGENT}/api/tunnels").json().get("tunnels", [])
        public = next((t["public_url"] for t in tunnels if t.get("proto") == "https"), "")
    except Exception:
        pass
    check("ngrok is running", bool(public), public or "no tunnel from the local ngrok agent",
          "start ngrok: ngrok http 8000 --url reprint-purveyor-foil.ngrok-free.dev")
    check("PUBLIC_URL matches the live tunnel", bool(public) and public.rstrip("/") == config.PUBLIC_URL,
          "same" if public.rstrip("/") == config.PUBLIC_URL else "PUBLIC_URL and the tunnel differ",
          "set PUBLIC_URL to the live tunnel in backend/.env, restart the backend, rerun setup_voice.py")
    reachable = False
    if config.PUBLIC_URL:
        try:
            reachable = http.get(f"{config.PUBLIC_URL}/health", timeout=20).status_code == 200
        except httpx.RequestError:
            reachable = False
    check("the tunnel reaches the backend", reachable, config.PUBLIC_URL,
          "ngrok is not forwarding to the backend port")
    try:
        front = http.get(FRONTEND, timeout=10).status_code
    except httpx.RequestError:
        front = 0
    check("frontend answers", front == 200, f"{FRONTEND} -> {front or 'no answer'}",
          "start the frontend: npm run dev in eride-repo")


# ---------------------------------------------------------------- the inbound path

def inbound() -> None:
    section("the inbound call path")
    token = config.API_TOKEN or config.API_SERVICE_TOKEN
    body = {}
    try:
        r = http.post(f"{config.PUBLIC_URL}/voice/initiation", json={"caller_id": CALLER, "probe": True},
                      headers={"X-Api-Key": token}, timeout=20)
        body = r.json() if r.status_code == 200 else {}
    except Exception:
        pass
    variables = body.get("dynamic_variables") or {}
    check("the initiation webhook answers through the tunnel", bool(variables),
          "no usable answer" if not variables else "200",
          "the webhook must answer, or the call drops before it connects")
    check("the caller is recognised", bool(variables.get("user_name")),
          f"greets {variables.get('user_name') or 'nobody'}",
          f"run demo_state.py so {CALLER} belongs to a seeded user")
    check("every dynamic variable comes back", set(variables) == set(voice.PLACEHOLDERS),
          f"{len(variables)} of {len(voice.PLACEHOLDERS)}",
          "a missing variable ends the call the moment it connects")
    check("the greeting names the caller", variables.get("user_name", "zzz") in variables.get("greeting", ""),
          (variables.get("greeting") or "")[:60])


# ---------------------------------------------------------------- the provider side

def providers() -> None:
    section("ElevenLabs and Twilio")
    agent, status = el(f"/agents/{config.ELEVENLABS_AGENT_ID}")
    check("the agent exists", bool(agent), f"HTTP {status}", "check ELEVENLABS_AGENT_ID")
    if agent:
        prompt = ((agent.get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}
        overrides = ((agent.get("platform_settings") or {}).get("overrides") or {})
        check("the agent model is the one we chose", prompt.get("llm") == config.ELEVENLABS_LLM,
              f"{prompt.get('llm')} vs {config.ELEVENLABS_LLM}",
              "rerun setup_voice.py, or set ELEVENLABS_LLM to the dashboard model")
        check("the agent prompt is the current one", prompt.get("prompt") == voice.AGENT_PROMPT,
              "live prompt matches app/voice.py" if prompt.get("prompt") == voice.AGENT_PROMPT
              else "the live prompt is stale",
              "rerun setup_voice.py to push the prompt in app/voice.py")
        check("the agent takes its variables from the webhook",
              overrides.get("enable_conversation_initiation_client_data_from_webhook") is True,
              fix="rerun setup_voice.py to opt the agent in")
        check("the agent allows the web widget", ((agent.get("platform_settings") or {}).get("auth")
                                                  or {}).get("enable_auth") is False,
              fix="allow unauthenticated web sessions for Talk to Eco, or expect the widget to refuse")

    mcp, status = el(f"/mcp-servers/{config.ELEVENLABS_MCP_SERVER_ID}")
    cfg = (mcp or {}).get("config") or {}
    check("the MCP server is registered", bool(mcp), f"HTTP {status}", "rerun setup_voice.py")
    check("the MCP server points at this tunnel", cfg.get("url") == f"{config.PUBLIC_URL}/mcp",
          cfg.get("url") or "unknown", "rerun setup_voice.py after PUBLIC_URL changed")
    check("the MCP transport is streamable http", cfg.get("transport") == "STREAMABLE_HTTP",
          cfg.get("transport") or "unknown")
    check("a slow tool will not be cut off", (cfg.get("response_timeout_secs") or 0) >= 20,
          f"response_timeout_secs={cfg.get('response_timeout_secs')}",
          "raise the MCP response timeout to at least 20 seconds")
    check(f"all {TOOLS} tools answer through the tunnel", mcp_tools() == TOOLS,
          f"{mcp_tools()} tools", "the backend or the tunnel is not serving /mcp")

    number, status = el(f"/phone-numbers/{config.ELEVENLABS_PHONE_NUMBER_ID}")
    assigned = ((number or {}).get("assigned_agent") or {}).get("agent_id")
    check("the Twilio number is imported", bool(number), f"HTTP {status}", "rerun setup_voice.py")
    check("the number is answered by our agent", assigned == config.ELEVENLABS_AGENT_ID,
          (number or {}).get("phone_number") or "unknown",
          "rerun setup_voice.py to bind the number to the agent")
    check("the number is the one being dialled",
          (number or {}).get("phone_number") == config.TWILIO_PHONE_NUMBER,
          f"{(number or {}).get('phone_number')} vs {config.TWILIO_PHONE_NUMBER}")

    hook = None
    settings_body, status = el("/settings")
    if settings_body:
        hook = (settings_body.get("conversation_initiation_client_data_webhook") or {}).get("url")
    check("the workspace webhook points at this tunnel", hook == f"{config.PUBLIC_URL}/voice/initiation",
          hook or f"HTTP {status}", "rerun setup_voice.py to move the webhook")

    try:
        r = http.get(f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}.json",
                     auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN), timeout=15)
        account = r.json() if r.status_code == 200 else {}
    except httpx.RequestError:
        account = {}
    check("Twilio credentials work", account.get("status") == "active",
          f"account {account.get('status') or 'unreachable'}, type {account.get('type', 'unknown')}",
          "check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
    if account.get("type") == "Trial":
        print("        note: a Twilio trial can only text numbers verified in the console")
    if config.TWILIO_SMS_TEMPLATE:
        print("        note: TWILIO_SMS_TEMPLATE is set, so a text carries the template id and not the"
              " ride details. The app shows the details instead.")


def mcp_tools() -> int:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async def go():
        token = config.API_TOKEN or config.API_SERVICE_TOKEN
        async with httpx2.AsyncClient(headers={"X-Api-Key": token}, timeout=20) as client:
            async with Client(streamable_http_client(f"{config.PUBLIC_URL}/mcp", http_client=client)) as c:
                return len((await c.list_tools()).tools)
    try:
        return asyncio.run(go())
    except Exception:
        return 0


# ---------------------------------------------------------------- the database

def database() -> None:
    section("demo data")
    from app import db
    try:
        # The embedded Postgres prints its own startup chatter; keep the report clean.
        with contextlib.redirect_stdout(io.StringIO()), db.conn() as c:
            users = c.execute("select count(*) as n from users").fetchone()["n"]
            cars = c.execute("select count(*) as n from vehicles where active").fetchone()["n"]
            waiting = c.execute("select u.name from trips t join users u on u.id = t.user_id"
                                " where t.status = 'open' and t.role = 'passenger'"
                                " order by t.id").fetchall()
            matches = c.execute("select count(*) as n from matches where status <> 'cancelled'").fetchone()["n"]
            runs = c.execute("select count(*) as n from agent_runs").fetchone()["n"]
            logins = {r["email"]: r["role"] for r in c.execute(
                "select a.email, a.role from auth_accounts a order by a.user_id")}
    except Exception as e:
        check("the database answers", False, type(e).__name__, "start the database or check DATABASE_URL")
        return
    check("the seeded people are there", users >= 7, f"{users} users", "run demo_state.py")
    check("all four demo cars are active", cars == 4, f"{cars} active", "run demo_state.py")
    check("Maya and Jordan are waiting", [r["name"] for r in waiting] == ["Maya", "Jordan"],
          ", ".join(r["name"] for r in waiting) or "nobody", "run demo_state.py")
    check("no stray matches", matches == 0, f"{matches} live matches", "run demo_state.py")
    check("the planner feed starts empty", runs == 0, f"{runs} agent runs", "run demo_state.py")
    expected = {email: role for _, _, email, _, role in demo_accounts.ACCOUNTS}
    check("every demo login exists", logins == expected,
          f"{len(logins)} of {len(expected)}", "run demo_state.py to recreate the logins")
    section("email")
    from app import notify
    if notify.email_configured():
        check("SMTP is configured, so confirmations will be sent for real", True)
    else:
        print(f"  NOTE  SMTP is not configured, so confirmations are written to"
              f" {Path(config.EMAIL_OUTBOX).name}")
    print(f"  NOTE  NOTIFY_ON_MATCH is {'on' if config.NOTIFY_ON_MATCH else 'off'}"
          f"{'' if config.NOTIFY_ON_MATCH else ', so no match texts will be sent'}")


def main() -> int:
    print(f"preflight for a call to {config.TWILIO_PHONE_NUMBER or '(no number)'} from {CALLER}")
    settings()
    local()
    inbound()
    providers()
    database()
    print()
    if failures:
        print(f"NOT READY: {len(failures)} thing(s) to fix")
        for item in dict.fromkeys(failures):
            print(f"  - {item}")
        return 1
    print("READY TO CALL")
    print(f"  dial {config.TWILIO_PHONE_NUMBER} from {CALLER}")
    print("  ask to drive to Meijer on Saturday around 2 and to borrow a car")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        from app import db
        db.close_pool()
