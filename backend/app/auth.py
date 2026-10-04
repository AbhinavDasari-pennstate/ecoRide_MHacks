"""Email accounts, opaque cookie sessions and HTTP authorization boundaries."""
import hashlib
import re
import secrets
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psycopg

from app import config, db

COOKIE = "eride_session"
SESSION_SECONDS = 60 * 60 * 24 * 7
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
# Bound the memory used by scrypt in this process (128 MiB per operation).
_password_slots = threading.BoundedSemaphore(2)
router = APIRouter(prefix="/auth")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        return value


class SignupIn(LoginIn):
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["rider", "owner"] = "rider"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Enter your name")
        return value


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _scrypt(password, salt):
    with _password_slots:
        return hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                              p=SCRYPT_P, maxmem=256 * 1024 * 1024, dklen=64)


def _hash_password(password):
    salt = secrets.token_bytes(16)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${_scrypt(password, salt).hex()}"


def _verify_password(password, encoded):
    # Unknown emails still do the same expensive derivation as existing accounts.
    salt, expected = bytes(16), bytes(64)
    if encoded:
        algorithm, n, r, p, salt_hex, hash_hex = encoded.split("$")
        if (algorithm, int(n), int(r), int(p)) != ("scrypt", SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(hash_hex)
    return secrets.compare_digest(_scrypt(password, salt), expected) and encoded is not None


def _throttle(request, email, operation):
    # Read only the ASGI client address. Uvicorn may derive it from X-Forwarded-For
    # only for explicitly trusted proxy peers; that edge must overwrite incoming
    # forwarding headers with the socket address (see README). Never parse XFF here.
    ip = request.client.host if request.client else "unknown"
    rules = [(f"{operation}:ip:{_digest(ip)}", 30), (f"{operation}:email:{_digest(email)}", 8)]
    limited = False
    with db.conn() as c:
        c.execute("delete from auth_rate_limits where started_at < now() - interval '1 day'")
        for key, maximum in rules:
            row = c.execute("insert into auth_rate_limits(key) values (%s) on conflict (key) do update set"
                            " attempts = case when auth_rate_limits.started_at < now() - interval '15 minutes'"
                            " then 1 else auth_rate_limits.attempts + 1 end,"
                            " started_at = case when auth_rate_limits.started_at < now() - interval '15 minutes'"
                            " then now() else auth_rate_limits.started_at end returning attempts", (key,)).fetchone()
            limited |= row["attempts"] > maximum
    if limited:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.", headers={"Retry-After": "900"})


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 200:
        return None
    with db.conn() as c:
        return c.execute("select u.id, u.name, a.email, a.role from auth_sessions s"
                         " join auth_accounts a on a.user_id = s.user_id join users u on u.id = a.user_id"
                         " where s.token_hash = %s and s.expires_at > now()", (_digest(token),)).fetchone()


def principal(request: Request):
    # A browser cookie never combines with an adapter token to gain privilege.
    if request.cookies.get(COOKIE):
        user = current_user(request)
        if user:
            return user
        raise HTTPException(401, "Please sign in again")
    authorization = request.headers.get("authorization", "")
    if config.API_SERVICE_TOKEN and secrets.compare_digest(
        authorization.encode(), f"Bearer {config.API_SERVICE_TOKEN}".encode()
    ):
        return {"service": True}
    raise HTTPException(401, "Sign in to continue")


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Sign in to continue")
    return user


def require_service(actor=Depends(principal)):
    if not actor.get("service"):
        raise HTTPException(403, "This operation is only available to a trusted server")
    return actor


def require_role(actor, *roles):
    if not actor.get("service") and actor["role"] not in roles:
        raise HTTPException(403, "Your account cannot access this feature")


def identity(actor, supplied=None):
    if actor.get("service"):
        if supplied is None:
            raise HTTPException(422, "A user ID is required for a trusted server operation")
        return supplied
    if supplied is not None and supplied != actor["id"]:
        raise HTTPException(403, "You can only act on your own account")
    return actor["id"]


def own_trip(actor, trip_id):
    if actor.get("service"):
        return
    require_role(actor, "rider", "owner")
    with db.conn() as c:
        row = c.execute("select user_id from trips where id = %s", (trip_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Trip not found")
    identity(actor, row["user_id"])


def own_vehicle(actor, vehicle_id):
    if actor.get("service"):
        return
    require_role(actor, "owner")
    with db.conn() as c:
        row = c.execute("select owner_id from vehicles where id = %s", (vehicle_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Vehicle not found")
    if row["owner_id"] != actor["id"]:
        raise HTTPException(403, "Only the vehicle owner can do this")


def own_booking(actor, booking_id):
    if actor.get("service"):
        return
    require_role(actor, "owner")
    with db.conn() as c:
        row = c.execute("select v.owner_id from bookings b join vehicles v on v.id = b.vehicle_id"
                        " where b.id = %s", (booking_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Booking not found")
    if row["owner_id"] != actor["id"]:
        raise HTTPException(403, "Only the vehicle owner can respond to this booking")


def match_access(actor, match_id, *, driver_only=False):
    if actor.get("service"):
        return
    require_role(actor, "rider", "owner")
    with db.conn() as c:
        row = c.execute("select t.user_id as driver_id, v.owner_id, exists ("
                        "select 1 from match_members mm join trips mt on mt.id = mm.trip_id"
                        " where mm.match_id = m.id and mt.user_id = %s and mm.status <> 'cancelled'"
                        ") as member from matches m join trips t on t.id = m.driver_trip_id"
                        " left join vehicles v on v.id = m.vehicle_id where m.id = %s",
                        (actor["id"], match_id)).fetchone()
    if not row:
        raise HTTPException(404, "Match not found")
    allowed = row["driver_id"] == actor["id"] if driver_only else row["member"] or row["owner_id"] == actor["id"]
    if not allowed:
        raise HTTPException(403, "This match is not available to your account")


def _new_session(c, request, response, user_id):
    old = request.cookies.get(COOKIE)
    if old:
        c.execute("delete from auth_sessions where token_hash = %s", (_digest(old),))
    c.execute("delete from auth_sessions where expires_at <= now()")
    token = secrets.token_urlsafe(32)
    c.execute("insert into auth_sessions(token_hash, user_id, expires_at)"
              " values (%s, %s, now() + interval '7 days')", (_digest(token), user_id))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=config.SESSION_COOKIE_SECURE, samesite="lax", path="/")


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, response: Response):
    _throttle(request, body.email, "signup")
    hashed = _hash_password(body.password)
    try:
        with db.conn() as c:
            roles = ["driver", "passenger"] + (["owner"] if body.role == "owner" else [])
            row = c.execute("insert into users(name, roles, home_lat, home_lng) values (%s,%s,%s,%s) returning id, name",
                            (body.name, roles, *config.ANN_ARBOR)).fetchone()
            c.execute("insert into auth_accounts(user_id, email, password_hash, role) values (%s,%s,%s,%s)",
                      (row["id"], body.email, hashed, body.role))
            _new_session(c, request, response, row["id"])
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "An account with this email already exists") from None
    return {"user": {**row, "email": body.email, "role": body.role}}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    _throttle(request, body.email, "login")
    with db.conn() as c:
        row = c.execute("select u.id, u.name, a.email, a.role, a.password_hash from auth_accounts a"
                        " join users u on u.id = a.user_id where a.email = %s", (body.email,)).fetchone()
    if not _verify_password(body.password, row["password_hash"] if row else None):
        raise HTTPException(401, "Email or password is incorrect")
    with db.conn() as c:
        _new_session(c, request, response, row["id"])
    return {"user": {key: row[key] for key in ("id", "name", "email", "role")}}


@router.get("/me")
def me(request: Request):
    return {"user": current_user(request)}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with db.conn() as c:
            c.execute("delete from auth_sessions where token_hash = %s", (_digest(token),))
    response.delete_cookie(COOKIE, httponly=True, secure=config.SESSION_COOKIE_SECURE, samesite="lax", path="/")
    return {"ok": True}
