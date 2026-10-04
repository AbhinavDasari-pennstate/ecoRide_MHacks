"""Voice agent and texting. An MCP server (mounted on the API at /mcp) gives the ElevenLabs voice agent
ride tools that call app.apply in-process, so a phone call follows the same rules as every other front
door. Calls go out through ElevenLabs on the Twilio number; texts go through Twilio.
Every figure a tool returns comes from code (match summaries), never from the voice LLM."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app import apply, config, notify

_http = httpx.Client(timeout=15.0)   # tests swap this for an httpx.MockTransport client

# ---------------------------------------------------------------- the agent (scripts/setup_voice.py pushes this to ElevenLabs)

AGENT_NAME = "ecoRide"
FIRST_MESSAGE = "{{greeting}}"
AGENT_PROMPT = """You are Eco, the phone voice of eCARide, a campus ride-sharing service in Ann Arbor. Students share rides
to places like Meijer, and eCARide picks the lowest-emission car for each group.

Say the company name out loud as "ee-car-ride", three beats. Never spell it out letter by letter.

Your opening line has already been spoken to the caller. Do not greet them again, do not say your name
again, and do not say "this is Eco" again. Carry on from their answer.

This call
- Caller's number: {{system__caller_id}} (empty in a browser test)
- Caller's name: {{user_name}} (blank means we did not recognise the number)
- Caller's user id: {{user_id}} (blank means we did not recognise the number)
- Call reason: {{call_reason}}. If it is not "inbound", you phoned {{user_name}} (user id {{user_id}}) about it.
  Their ride: {{ride_summary}}

How to help
1. If the caller's user id above is filled in, you already know who this is. Use that user id and do not call
   find_caller. Only when it is blank, call find_caller with the caller's number, and if that fails or the
   number is empty, ask for their phone number and try again.
2. To book, collect the destination, the day and time, and whether they will drive (and if so, whether they need a car).
   "Around 2" means a window from 1:45 to 2:30. Times are Ann Arbor local time; find_caller tells you today's date.
   Say one short line such as "One moment while I book that" and then call request_ride once.
3. To confirm a ride call accept_ride. A car owner approving their car: approve_car. To cancel: cancel_ride.
   To check on rides: my_rides.
4. After booking or confirming, offer once to text the details with text_ride_details. If they already have the
   text, do not offer again.
5. Read the "say" text from a tool as written. Never make up prices, times, distances, CO2 figures or names; use only
   what tools return. If a tool returns "error", explain it simply and offer a next step.

Never repeat work
- Call each tool at most once for the same request. If you have already called request_ride for this booking,
  do not call it again, even if the caller repeats themselves or you are unsure it worked: call my_rides instead
  and read what it returns.
- A tool that takes a few seconds is still working. Wait for its answer rather than calling it a second time.
- Never use call_rider on the person you are already speaking to.

Style: this is a phone call. Keep each reply to one or two short sentences and ask one question at a time."""
# defaults for the variables above; outbound calls override them (call_user)
PLACEHOLDERS = {"greeting": "Hi, this is Eco from eCARide. Do you want to book a ride, or check on one?",
                "call_reason": "inbound", "user_id": "", "user_name": "", "ride_summary": ""}

# ---------------------------------------------------------------- texts and calls

def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}


def send_sms(to: str, body: str) -> dict:
    """Text through Twilio. A trial account only sends a template id (TWILIO_SMS_TEMPLATE) to verified numbers."""
    sid, token, frm = config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN, config.TWILIO_PHONE_NUMBER
    if not (sid and token and frm):
        raise ValueError("texting is not set up (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER)")
    try:
        r = _http.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", auth=(sid, token),
                       data={"From": frm, "To": to, "Body": config.TWILIO_SMS_TEMPLATE or body})
    except httpx.RequestError:
        raise ValueError("Twilio text status is uncertain after a network error; check delivery before sending another text") from None
    data = _json(r)
    if r.status_code >= 400:
        raise ValueError(f"Twilio refused the text: {data.get('message', r.status_code)} (code {data.get('code')})")
    return {"sid": data.get("sid"), "status": data.get("status")}


def _latest(user_id: int) -> tuple[dict, str]:
    """(user, summary of their newest ride that has a match, or '')."""
    rides = apply.user_rides(user_id)
    return rides["user"], next((r["summary"] for r in rides["rides"] if r["match_id"]), "")


def text_ride(user_id: int, match_id: int | None = None) -> dict:
    """Text someone the code-written summary of a ride (their latest one by default).

    Sent at most once per person, ride and wording inside notify.TEXT_REPEAT_MINUTES, so a
    repeated tool call or a second press of the button does not text them twice."""
    user, summary = _latest(user_id)
    if match_id is not None:
        m = apply.get_match(match_id)
        if not m:
            raise LookupError(f"no match with id {match_id}")
        summary = m["summary"]
    if not summary:
        raise ValueError(f"{user['name']} has no ride to text about yet")
    subject = f"match:{match_id}" if match_id is not None else "latest"
    state = notify.state_hash(summary)
    if notify.already_sent("sms", "ride_details", user_id, subject, state):
        return {"to": user["name"], "sent": False, "reason": "already_sent",
                "say": "I already texted you those details, so they should be on your phone."}
    out = send_sms(user["phone"], f"eCARide: {summary}")
    notify.record_sent("sms", "ride_details", user_id, subject, state, match_id=match_id)
    return {"to": user["name"], "sent": True, "say": "Sent. The details are on their way by text.", **out}


def call_user(user_id: int, reason: str) -> dict:
    """Outbound call: the ElevenLabs agent phones the user from the Twilio number."""
    if not (config.ELEVENLABS_API_KEY and config.ELEVENLABS_AGENT_ID and config.ELEVENLABS_PHONE_NUMBER_ID):
        raise ValueError("calling is not set up (run scripts/setup_voice.py)")
    user, summary = _latest(user_id)
    # Never ring the person already on the line, and never ring anyone twice in a few minutes.
    if guard := notify.call_guard(user_id):
        return {"calling": user["name"], "placed": False, "reason": guard["reason"], "say": guard["say"]}
    try:
        r = _http.post("https://api.elevenlabs.io/v1/convai/twilio/outbound-call",
                       headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                       json={"agent_id": config.ELEVENLABS_AGENT_ID, "agent_phone_number_id": config.ELEVENLABS_PHONE_NUMBER_ID,
                             "to_number": user["phone"], "conversation_initiation_client_data": {"dynamic_variables": {
                                 "greeting": f"Hi {user['name']}, this is Eco from eCARide, calling about your ride.",
                                 "call_reason": reason, "user_id": str(user["id"]), "user_name": user["name"],
                                 "ride_summary": summary}}})
    except httpx.RequestError:
        raise ValueError("ElevenLabs call status is uncertain after a network error; check before placing another call") from None
    data = _json(r)
    if r.status_code >= 400 or data.get("success") is False:
        raise ValueError(f"ElevenLabs could not place the call: {data.get('detail') or data.get('message') or r.status_code}")
    notify.record_outbound_call(user_id, reason)
    return {"calling": user["name"], "conversation_id": data.get("conversation_id")}


def initiation(caller_id: str | None) -> dict:
    """ElevenLabs asks who is calling before an inbound call connects. Every variable the prompt and the
    first message use has to come back or the call drops at once, so start from PLACEHOLDERS and never
    raise: an unrecognised number still gets a working conversation, and the agent asks for it instead."""
    variables = dict(PLACEHOLDERS)   # call_reason "inbound", a generic greeting, no user
    try:
        user, summary = _latest(apply.find_user(caller_id or "")["id"])
        variables |= {"user_id": str(user["id"]), "user_name": user["name"], "ride_summary": summary,
                      "greeting": f"Hi {user['name']}, this is Eco from eCARide."
                                  " Do you want to book a ride, or check on one?"}
    except (LookupError, ValueError):
        pass
    return {"type": "conversation_initiation_client_data", "dynamic_variables": variables}


# ---------------------------------------------------------------- MCP tools for the agent

mcp = MCPServer(name="ecoRide", instructions=(
    "Campus ride-sharing tools for eCARide in Ann Arbor. Identify the person first (find_caller), then book, check, "
    "accept or cancel rides. Read each 'say' text back as written: it holds the only correct prices, times and CO2."))


def _try(fn) -> dict:
    """Errors come back as {'error': ...} so the agent can tell the caller what went wrong."""
    try:
        return fn()
    except (LookupError, ValueError) as e:
        return {"error": str(e)}


def _rides(user_id: int) -> list[dict]:
    return [{k: r[k] for k in ("trip_id", "match_id", "status", "summary")} for r in apply.user_rides(user_id)["rides"]]


@mcp.tool()
def find_caller(phone: str) -> dict:
    """Find the person by phone number (any format). Call this first with the caller's number.
    Returns user_id, name, roles, their latest rides, and the current local date and time."""
    def run():
        u = apply.find_user(phone)
        now = datetime.now(ZoneInfo(config.TIMEZONE))
        return {"user_id": u["id"], "name": u["name"], "roles": u["roles"],
                "now": f"{now:%A %Y-%m-%d %H:%M} Ann Arbor time", "rides": _rides(u["id"])}
    return _try(run)


@mcp.tool()
def request_ride(user_id: int, destination: str, earliest: str, latest: str | None = None,
                 role: str = "passenger", needs_car: bool | None = None, party_size: int = 1) -> dict:
    """Post a trip and plan it right away (takes a few seconds). Safe to repeat: calling this again with
    the same destination, role and overlapping window returns the trip already booked instead of a second one.
    destination: a place name such as "Meijer". earliest/latest: the departure window in Ann Arbor local time,
    ISO format like 2026-10-10T13:45 (latest defaults to 45 minutes after earliest). role: "driver" if they will
    drive, otherwise "passenger". needs_car: for drivers without their own car (defaults to true for drivers)."""
    def run():
        start = datetime.fromisoformat(earliest)
        end = datetime.fromisoformat(latest) if latest else start + timedelta(minutes=45)
        existing = apply.find_duplicate_trip(user_id, role, destination, start, end)
        if existing:
            matches = apply.matches_for_trip(existing["id"])
            say = ("That is already booked. " + matches[0]["summary"]) if matches else (
                f"That is already booked: your trip to {existing['dest_name']} is posted."
                " There's no match yet; check your rides later.")
            return {"trip_id": existing["id"], "match_id": matches[0]["id"] if matches else None,
                    "already_booked": True, "say": say}
        trip = apply.create_trip({"user_id": user_id, "role": role, "dest_name": destination, "window_start": start,
                                  "window_end": end, "party_size": party_size, "needs_vehicle": needs_car})
        apply.run_planning("voice_request", trip["id"], mode=config.VOICE_PLANNER or None)
        matches = apply.matches_for_trip(trip["id"])
        if matches:
            return {"trip_id": trip["id"], "match_id": matches[0]["id"], "already_booked": False,
                    "say": matches[0]["summary"]}
        return {"trip_id": trip["id"], "match_id": None, "already_booked": False,
                "say": f"Your trip to {trip['dest_name']} is posted. There's no match yet; check your rides later."}
    return _try(run)


@mcp.tool()
def my_rides(user_id: int) -> dict:
    """The person's latest trips with the status of each ride, as sentences to read out."""
    return _try(lambda: {"rides": _rides(user_id)})


@mcp.tool()
def accept_ride(user_id: int, match_id: int) -> dict:
    """The person confirms their place on a proposed ride (driver or passenger). Safe to repeat."""
    return _try(lambda: {"match_id": match_id, "say": apply.accept(match_id, user_id)["summary"]})


@mcp.tool()
def approve_car(user_id: int, match_id: int) -> dict:
    """A car owner approves lending their car for a ride. Safe to repeat."""
    return _try(lambda: {"match_id": match_id, "say": apply.approve_for_owner(user_id, match_id)["match"]["summary"]})


@mcp.tool()
def cancel_ride(user_id: int, trip_id: int) -> dict:
    """Cancel one of the person's trips. The rest of the group is replanned automatically. Safe to repeat."""
    def run():
        out = apply.cancel_trip(trip_id, user_id=user_id)
        say = f"Your trip to {out['trip']['dest_name']} is cancelled."
        return {"trip_id": trip_id, "say": say + (" The rest of the group has been replanned." if out["replans"] else "")}
    return _try(run)


@mcp.tool()
def text_ride_details(user_id: int, match_id: int | None = None) -> dict:
    """Text the person the details of a ride (their latest ride if match_id is not given). Safe to repeat:
    the same details are never texted to the same person twice in a few minutes."""
    return _try(lambda: text_ride(user_id, match_id))


@mcp.tool()
def call_rider(user_id: int, reason: str) -> dict:
    """Have the voice agent phone someone else, e.g. to ask a passenger to confirm. reason: a short phrase.
    Never use this on the person you are already speaking to; it will refuse and tell you so."""
    return _try(lambda: call_user(user_id, reason))


# Streamable HTTP, stateless JSON: no sessions to lose across reloads, and simple for ElevenLabs.
# ponytail: DNS-rebinding protection would reject a tunnel's Host header; API_TOKEN guards the endpoint instead
mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True,
                                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
