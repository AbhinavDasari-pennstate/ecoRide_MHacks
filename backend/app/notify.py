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
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

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


# ---------------------------------------------------------------- email

SUBJECT = "Your ecoRide trip is confirmed"


def email_configured() -> bool:
    return all((config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                config.SMTP_PASSWORD, config.EMAIL_FROM))


def _body(match: dict) -> str:
    """The same wording, fare and CO2 figures the app and the agent use. Code computed all of them."""
    depart = datetime.fromisoformat(match["depart_time"]).astimezone(ZoneInfo(config.TIMEZONE))
    impact = match.get("impact") or {}
    vehicle = match.get("vehicle") or {}
    lines = [
        "Your ecoRide trip is confirmed.",
        "",
        match["summary"],
        "",
        f"Departure: {depart:%A %d %B} at {depart:%I:%M %p} ({config.TIMEZONE})",
        f"Vehicle: {vehicle.get('make_model', 'the driver and their own car')}",
    ]
    if match.get("cost_per_person_cents") is not None:
        lines.append(f"Cost per person: ${match['cost_per_person_cents'] / 100:.2f}")
    if impact.get("kg_co2_avoided") is not None:
        lines.append(f"CO2 avoided versus everyone driving separately: {impact['kg_co2_avoided']:.2f} kg"
                     f" ({impact.get('percent_reduction', 0):.0f}% less)")
        equivalents = impact.get("equivalents") or {}
        if equivalents:
            lines.append(f"About {equivalents.get('tree_seedlings_10yr')} tree seedlings grown for ten"
                         f" years, or {equivalents.get('smartphone_charges')} smartphone charges.")
    lines += ["", "These are projected estimates, not measured emissions.", "", "ecoRide, Ann Arbor"]
    return "\n".join(lines)


def _write_outbox(to: str, subject: str, body: str) -> None:
    """No SMTP configured, so keep the message where it can still be read out."""
    stamp = datetime.now(timezone.utc).astimezone(ZoneInfo(config.TIMEZONE))
    block = (f"\n{'=' * 78}\n{stamp:%Y-%m-%d %H:%M:%S %Z}\nTo: {to}\nSubject: {subject}\n"
             f"{'-' * 78}\n{body}\n")
    path = Path(config.EMAIL_OUTBOX)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(block)


def send_email(to: str, subject: str, body: str) -> str:
    """-> "smtp" when it left the building, "outbox" when it was written to the local log.
    Never logs the body, the address or the credentials."""
    if not email_configured():
        _write_outbox(to, subject, body)
        return "outbox"
    message = EmailMessage()
    message["From"] = config.EMAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    port = int(config.SMTP_PORT or 587)
    if port == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, port, timeout=20) as server:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(config.SMTP_HOST, port, timeout=20) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message)
    return "smtp"


def _email_audience(c, match: dict) -> list[dict]:
    """Travellers who have a web account to email. The car's owner is told by text, not email."""
    ids = [m["user_id"] for m in match["members"] if m["status"] != "cancelled"]
    if not ids:
        return []
    return c.execute("select a.user_id as id, a.email, u.name from auth_accounts a"
                     " join users u on u.id = a.user_id where a.user_id = any(%s::int[]) order by a.user_id",
                     (ids,)).fetchall()


def email_confirmation(match_id: int) -> list[dict]:
    """One confirmation per rider per confirmed ride, deduped exactly like the texts. Never raises."""
    try:
        from app import apply
        match = apply.get_match(match_id)
        if not match or match["status"] != "confirmed":
            return []
        state = _match_state(match)
        body = _body(match)
        with db.conn() as c:
            people = _email_audience(c, match)
        out = []
        for person in people:
            if already_sent("email", "confirmed", person["id"], f"match:{match_id}", state,
                            within_minutes=MATCH_REPEAT_MINUTES):
                continue
            try:
                where = send_email(person["email"], SUBJECT, body)
            except Exception as e:
                log.warning("confirmation email failed for user %s (%s)", person["id"], type(e).__name__)
                continue                     # no ledger row, so a later retry can still deliver it
            record_sent("email", "confirmed", person["id"], f"match:{match_id}", state,
                        match_id=match_id, delivered=where)
            out.append({"user_id": person["id"], "delivered": where})
        return out
    except Exception as e:
        log.warning("confirmation emails failed (%s); the ride itself is unaffected", type(e).__name__)
        return []


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
        if notice == "confirmed":
            delivered += email_confirmation(match_id)
        return delivered
    except Exception as e:
        log.warning("match notices failed (%s); the ride itself is unaffected", type(e).__name__)
        return []
