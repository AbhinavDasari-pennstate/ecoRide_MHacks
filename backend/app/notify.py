"""Send-once ledger for every outbound message and call.

Each text, call and email is written to `events` before it is considered done, keyed by
(channel, kind, user, subject, state). A retried voice tool call, a replan loop or a second
operator pressing the same button then finds the earlier row and stops, so nobody is called
or texted twice for the same thing.

Nothing here raises: a ledger read that fails allows the action (we would rather send than
drop a confirmation), and a ledger write that fails is logged and ignored. Never log message
bodies, phone numbers or credentials.
"""
import hashlib
import logging

from app import config, db

log = logging.getLogger(__name__)

LEDGER = "notification_sent"        # a text, email or in-app notice we delivered
OUTBOUND_CALL = "outbound_call_placed"
INBOUND_CALL = "voice_call_started"

# How long a record blocks a repeat.
TEXT_REPEAT_MINUTES = 10
CALL_REPEAT_MINUTES = 5
ON_CALL_MINUTES = 10               # someone who just reached the agent counts as still on the line


def state_hash(text: str) -> str:
    """Short digest of the exact wording we are about to send, so a changed ride sends again."""
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def _find(kind: str, within_minutes: int, fields: dict) -> dict | None:
    clauses = "".join(" and payload->>%s = %s" for _ in fields)
    args: list = [kind, within_minutes]
    for key, value in fields.items():
        args += [key, str(value)]
    try:
        with db.conn() as c:
            return c.execute(
                "select id, ts, payload from events where kind = %s"
                f" and ts > now() - make_interval(mins => %s){clauses} order by id desc limit 1",
                args).fetchone()
    except Exception as e:   # a ledger we cannot read must not block the demo
        log.warning("send-once ledger read failed (%s); allowing the send", type(e).__name__)
        return None


def _record(kind: str, payload: dict) -> None:
    try:
        with db.conn() as c:
            db.event(c, kind, payload)
    except Exception as e:
        log.warning("send-once ledger write failed (%s); continuing", type(e).__name__)


# ---------------------------------------------------------------- texts and emails

def already_sent(channel: str, kind: str, user_id: int, subject: str, state: str,
                 within_minutes: int = TEXT_REPEAT_MINUTES) -> bool:
    return _find(LEDGER, within_minutes, {"channel": channel, "notice": kind,
                                          "user_id": user_id, "subject": subject, "state": state}) is not None


def record_sent(channel: str, kind: str, user_id: int, subject: str, state: str, **extra) -> None:
    _record(LEDGER, {"channel": channel, "notice": kind, "user_id": user_id,
                     "subject": subject, "state": state, **extra})


# ---------------------------------------------------------------- calls

def record_inbound_call(user_id) -> None:
    """The initiation webhook identified a caller, so this person is on the line right now."""
    if user_id in (None, "", 0):
        return
    _record(INBOUND_CALL, {"user_id": int(user_id)})


def record_outbound_call(user_id: int, reason: str) -> None:
    _record(OUTBOUND_CALL, {"user_id": user_id, "reason": reason})


def call_guard(user_id: int) -> dict | None:
    """None means it is safe to place the call. Otherwise a reason and a line the agent can read."""
    if _find(INBOUND_CALL, ON_CALL_MINUTES, {"user_id": user_id}):
        return {"reason": "already_on_this_call",
                "say": "You are on the line with me right now, so there is no need for me to call you back."}
    if _find(OUTBOUND_CALL, CALL_REPEAT_MINUTES, {"user_id": user_id}):
        return {"reason": "called_recently",
                "say": "I called them a few minutes ago, so I will leave it with them for now."}
    return None


# ---------------------------------------------------------------- match notices

NOTICES = {
    "proposed": "We found you a ride.",
    "confirmed": "Your ride is confirmed.",
    "vehicle_changed": "Your ride changed to another car.",
}
# A match can be replanned many times; the ledger key below is what stops a loop from texting.
MATCH_REPEAT_MINUTES = 24 * 60
_warned_about_template = False


def texts_carry_details() -> bool:
    """A Twilio trial can only send a template id, so the ride details never reach the phone."""
    return not config.TWILIO_SMS_TEMPLATE


def texting_on() -> bool:
    return config.NOTIFY_ON_MATCH and bool(
        config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_PHONE_NUMBER)


def _notice_for(match: dict) -> str | None:
    if match["status"] == "confirmed":
        return "confirmed"
    if match["status"] in ("cancelled", "at_risk"):
        return None                       # nothing useful to tell anyone yet
    change = match.get("last_change") or {}
    before = (change.get("before") or {}).get("vehicle") or {}
    after = (change.get("after") or {}).get("vehicle") or {}
    if change and before.get("id") != after.get("id"):
        return "vehicle_changed"
    return "proposed"


def _match_state(match: dict) -> str:
    """What makes a ride materially different: which car, when, the fare and the pickup order.

    Deliberately not the summary sentence. That sentence also tracks who has accepted so far, so
    hashing it would re-announce the same ride to everyone on every single acceptance."""
    return state_hash("|".join(str(match.get(k)) for k in
                               ("vehicle_id", "depart_time", "cost_per_person_cents", "pickup_order")))


def _audience(c, match: dict) -> list[dict]:
    """Everyone with a stake in this ride: the travellers, plus the car's owner."""
    ids = {m["user_id"] for m in match["members"] if m["status"] != "cancelled"}
    owner = (match.get("vehicle") or {}).get("owner_id")
    if owner:
        ids.add(owner)
    if not ids:
        return []
    return c.execute("select id, name, phone from users where id = any(%s::int[]) order by id",
                     (sorted(ids),)).fetchall()


def match_state_changed(match_id: int) -> list[dict]:
    """Call once the transaction has committed. Delivers at most one notice per person, ride,
    event and wording, so a replan loop cannot text anyone twice. Never raises."""
    global _warned_about_template
    try:
        from app import apply, voice      # imported late: both modules import this one
        match = apply.get_match(match_id)
        if not match:
            return []
        notice = _notice_for(match)
        if not notice:
            return []
        state = _match_state(match)
        text = f"ecoRide: {NOTICES[notice]} {match['summary']}"
        by_sms = texting_on()
        if by_sms and not texts_carry_details():
            if not _warned_about_template:
                log.warning("TWILIO_SMS_TEMPLATE is set, so a text can only carry the template id and not"
                            " the ride details. Showing these notices in the app instead.")
                _warned_about_template = True
            by_sms = False
        with db.conn() as c:
            people = _audience(c, match)
        delivered = []
        for person in people:
            if already_sent("match", notice, person["id"], f"match:{match_id}", state,
                            within_minutes=MATCH_REPEAT_MINUTES):
                continue
            channel = "in_app"
            if by_sms and person["phone"]:
                try:
                    voice.send_sms(person["phone"], text)
                    channel = "sms"
                except Exception as e:     # a refused text still leaves the in-app notice
                    log.warning("match notice text failed for user %s (%s)", person["id"], type(e).__name__)
            record_sent("match", notice, person["id"], f"match:{match_id}", state,
                        match_id=match_id, text=text, delivered=channel)
            delivered.append({"user_id": person["id"], "notice": notice, "delivered": channel})
        return delivered
    except Exception as e:
        log.warning("match notices failed (%s); the ride itself is unaffected", type(e).__name__)
        return []
