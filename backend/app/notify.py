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

from app import db

log = logging.getLogger(__name__)

LEDGER = "notification_sent"        # a text or email we actually sent
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
