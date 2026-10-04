"""HTTP layer: thin routes over app.apply, plus the voice agent's MCP server at /mcp.
Run with `uvicorn app.main:app` from the backend root. LookupError -> 404, ValueError -> 422.
Planning after POST /trips runs as a background task (or inline with ?wait=true); the other state
changes replan synchronously inside apply and return the diff."""
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
import psycopg
from psycopg_pool import PoolTimeout

from app import apply, auth, config, db, notify, voice


@asynccontextmanager
async def lifespan(app):
    sm = voice.mcp.session_manager
    sm._has_started = False   # ponytail: the SDK refuses a 2nd run() though run() fully resets on exit; tests start the app many times
    async with sm.run():      # the mounted MCP app's lifespan doesn't run on its own
        yield
    db.close_pool()


def service_only(asgi):
    """Guards the mounted MCP app (FastAPI dependencies don't reach mounts): the voice agent sends the
    service token as `X-Api-Key` or `Authorization: Bearer`. No token configured = closed."""
    async def gate(scope, receive, send):
        if scope["type"] == "http" and scope["method"] != "OPTIONS":
            h = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if not auth.service_token_ok(h.get("x-api-key") or h.get("authorization", "").removeprefix("Bearer ")):
                return await JSONResponse({"detail": "missing or wrong API token"}, status_code=401)(scope, receive, send)
        await asgi(scope, receive, send)
    return gate


app = FastAPI(title="Campus Rides", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)


@app.middleware("http")
async def protect_browser_requests(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if ((origin is not None and origin.rstrip("/") not in config.CORS_ORIGINS)
                or (origin is None and request.headers.get("sec-fetch-site") == "cross-site")):
            return JSONResponse({"detail": "This request origin is not allowed"}, status_code=403,
                                headers={"Cache-Control": "no-store"})
    response = await call_next(request)
    # Account and trip data must not survive in shared caches or the PWA cache.
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(psycopg.IntegrityError)
def _conflict(request, e):
    return JSONResponse({"detail": "Database constraint conflict; reload current state and retry"}, status_code=409)


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
def _database_unavailable(request, e):
    return JSONResponse({"detail": "Database unavailable"}, status_code=503)


@app.exception_handler(LookupError)
def _not_found(request, e):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(ValueError)
def _bad_input(request, e):
    return JSONResponse({"detail": str(e)}, status_code=422)


# ---------------------------------------------------------------- request bodies (None = apply's default)

class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class IdentityIn(InputModel):
    provider: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=255)


class UserIn(IdentityIn):
    name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    roles: list[Literal["driver", "passenger", "owner"]] = Field(default_factory=list)
    home_lat: float = Field(ge=-90, le=90)
    home_lng: float = Field(ge=-180, le=180)


class TripIn(InputModel):
    user_id: Optional[int] = None
    role: Literal["driver", "passenger"]
    dest_name: str
    window_start: datetime        # naive = America/Detroit local
    window_end: datetime
    origin_lat: Optional[float] = None    # default: the user's home
    origin_lng: Optional[float] = None
    dest_lat: Optional[float] = None      # missing -> geocoded from dest_name
    dest_lng: Optional[float] = None
    dest_place_id: Optional[str] = None
    party_size: Optional[int] = None
    max_detour_mi: Optional[float] = None
    needs_vehicle: Optional[bool] = None  # default: true for drivers


class TripPatch(InputModel):
    dest_name: Optional[str] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lng: Optional[float] = None
    dest_place_id: Optional[str] = None
    party_size: Optional[int] = None
    max_detour_mi: Optional[float] = None
    needs_vehicle: Optional[bool] = None


class VehicleIn(InputModel):
    make_model: str
    fuel_type: Literal["ev", "gas"]
    seats: int                    # total occupants incl. driver
    range_mi: float
    efficiency: float             # kWh/mi (ev) or mpg (gas)
    efficiency_source: str = Field(default="Owner-supplied estimate; not independently verified", min_length=1, max_length=1000)
    price_per_hour_cents: int
    avail_start: datetime
    avail_end: datetime
    owner_id: Optional[int] = None
    lat: Optional[float] = None   # default: the owner's home
    lng: Optional[float] = None


class AcceptIn(InputModel):
    user_id: Optional[int] = None


class LocationIn(InputModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: Optional[float] = Field(default=None, ge=0, le=100_000)


class VehicleChoiceIn(InputModel):
    vehicle_id: int = Field(gt=0)


class TextIn(InputModel):
    match_id: Optional[int] = None   # default: the user's latest ride


class CallIn(InputModel):
    reason: str = Field(min_length=1, max_length=200)   # short phrase the agent opens with, e.g. "confirm your seat"


class InitiationIn(BaseModel):
    # ElevenLabs also sends agent_id, called_number, call_sid and conversation_id; only the caller matters.
    caller_id: Optional[str] = None
    # Set by scripts/preflight.py so a readiness check does not count as a call in progress.
    # ElevenLabs never sends this.
    probe: bool = False


class PlannerRunIn(InputModel):
    trip_id: Optional[int] = None
    match_id: Optional[int] = None
    dry_run: bool = False
    plan: Optional[dict] = None   # manual plan (fixtures): skips the planner, still completed + validated
    mode: Optional[Literal["gemini", "deterministic"]] = None


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {"ok": True, "planner": config.PLANNER, "maps": "live" if config.MAPS_SERVER_KEY else "offline",
            "gemini": "configured" if config.GEMINI_API_KEY else "missing",
            "voice": "configured" if config.ELEVENLABS_AGENT_ID and config.ELEVENLABS_PHONE_NUMBER_ID else "missing",
            "sms": "configured" if config.TWILIO_ACCOUNT_SID and config.TWILIO_PHONE_NUMBER else "missing"}


@app.post("/demo/bootstrap")
def demo_bootstrap(actor=Depends(auth.require_service)):
    return apply.demo_bootstrap()


@app.post("/demo/trips")
def demo_start(actor=Depends(auth.require_service)):
    return apply.demo_start()


@app.post("/demo/restart")
def demo_restart(actor=Depends(auth.require_service)):
    return apply.demo_restart()


@app.post("/matches/{match_id}/vehicle")
def select_vehicle(match_id: int, body: VehicleChoiceIn, actor=Depends(auth.principal)):
    auth.match_access(actor, match_id, driver_only=True)
    return apply.select_vehicle(match_id, body.vehicle_id)


@app.get("/ready")
def ready(actor=Depends(auth.require_service)):
    with db.conn() as c:
        if not c.execute("select to_regclass('schema_migrations') as name").fetchone()["name"]:
            raise HTTPException(503, "Database schema missing; run scripts/migrate.py")
        applied = {r["name"] for r in c.execute("select name from schema_migrations")}
        if any(p.name not in applied for p in db.MIGRATIONS.glob("*.sql")):
            raise HTTPException(503, "Database migrations pending; run scripts/migrate.py")
    return {"ok": True, "database": "connected"}


@app.post("/users")
def create_user(body: UserIn, actor=Depends(auth.require_service)):
    return apply.create_user(body.model_dump())


@app.post("/users/{user_id}/identities")
def link_identity(user_id: int, body: IdentityIn, actor=Depends(auth.require_service)):
    return apply.link_identity(user_id, body.provider, body.subject)


@app.get("/users/{user_id}/dashboard")
def dashboard(user_id: int, actor=Depends(auth.principal)):
    auth.identity(actor, user_id)
    return apply.dashboard(user_id)


@app.get("/me/dashboard")
def my_dashboard(actor=Depends(auth.require_user)):
    return apply.dashboard(actor["id"])


@app.get("/me/notifications")
def my_notifications(limit: int = Query(20, ge=1, le=100), actor=Depends(auth.require_user)):
    """The signed-in account's own ride notices. Shown in the app whether or not a text went out."""
    return apply.my_notifications(actor["id"], limit)


@app.get("/vehicles")
def vehicles(owner_id: Optional[int] = None, active: Optional[bool] = True,
             limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
             actor=Depends(auth.principal)):
    if not actor.get("service"):
        auth.require_role(actor, "rider", "owner")
        owner_id = auth.identity(actor, owner_id)
        if actor["role"] != "owner":
            return []
    return apply.list_vehicles(owner_id, active, limit, offset)


@app.post("/trips")
def create_trip(body: TripIn, tasks: BackgroundTasks, wait: bool = False, actor=Depends(auth.principal)):
    auth.require_role(actor, "rider", "owner")
    trip = apply.create_trip({**body.model_dump(), "user_id": auth.identity(actor, body.user_id)})
    if wait:   # voice and chat clients want the answer in the same request
        apply.run_planning("trip_created", trip["id"])
        return {"trip": trip, "planning": "done", "matches": apply.matches_for_trip(trip["id"])}
    tasks.add_task(apply.run_planning, "trip_created", trip["id"])
    return {"trip": trip, "planning": "queued"}


# Voice and texting: trusted server callers only (phone lookups would leak who uses the app).

@app.get("/users")
def find_user(phone: str, actor=Depends(auth.require_service)):
    return apply.find_user(phone)


@app.get("/users/{user_id}/rides")
def user_rides(user_id: int, actor=Depends(auth.require_service)):
    return apply.user_rides(user_id)


@app.post("/users/{user_id}/text")
def text_user(user_id: int, body: TextIn, actor=Depends(auth.require_service)):
    return voice.text_ride(user_id, body.match_id)


@app.post("/users/{user_id}/call")
def call_user(user_id: int, body: CallIn, actor=Depends(auth.require_service)):
    return voice.call_user(user_id, body.reason)


@app.post("/voice/initiation")
def voice_initiation(body: InitiationIn, actor=Depends(auth.require_service)):
    """ElevenLabs' conversation initiation webhook for inbound calls: the caller's dynamic variables.
    setup_voice.py registers the URL with the service token as its X-Api-Key header."""
    data = voice.initiation(body.caller_id)
    # Remember who is on the line, so call_rider cannot ring the caller back mid-call.
    if not body.probe:
        notify.record_inbound_call(data["dynamic_variables"].get("user_id"))
    return data


@app.patch("/trips/{trip_id}")
def update_trip(trip_id: int, body: TripPatch, actor=Depends(auth.principal)):
    auth.own_trip(actor, trip_id)
    result = apply.update_trip(trip_id, body.model_dump(exclude_unset=True))
    return result if actor.get("service") else {"trip": result["trip"], "planning": "completed"}


@app.post("/trips/{trip_id}/cancel")
def cancel_trip(trip_id: int, actor=Depends(auth.principal)):
    auth.own_trip(actor, trip_id)
    result = apply.cancel_trip(trip_id)
    return result if actor.get("service") else {"trip": result["trip"]}


@app.get("/trips/{trip_id}/matches")
def trip_matches(trip_id: int, actor=Depends(auth.principal)):
    auth.own_trip(actor, trip_id)
    return apply.matches_for_trip(trip_id)


@app.get("/matches/{match_id}")
def get_match(match_id: int, actor=Depends(auth.principal)):
    auth.match_access(actor, match_id)
    m = apply.get_match(match_id)
    if m is None:
        raise HTTPException(404, f"no match with id {match_id}")
    return m


@app.post("/matches/{match_id}/accept")
def accept(match_id: int, body: Optional[AcceptIn] = None, actor=Depends(auth.principal)):
    auth.require_role(actor, "rider", "owner")
    auth.match_access(actor, match_id)
    return apply.accept(match_id, auth.identity(actor, body.user_id if body else None))


@app.post("/matches/{match_id}/location")
def share_location(match_id: int, body: LocationIn, actor=Depends(auth.require_user)):
    auth.match_access(actor, match_id)
    return apply.share_location(match_id, actor["id"], body.lat, body.lng, body.accuracy_m)


@app.get("/matches/{match_id}/locations")
def live_locations(match_id: int, actor=Depends(auth.require_user)):
    auth.match_access(actor, match_id)
    return apply.live_locations(match_id, actor["id"])


@app.post("/vehicles")
def create_vehicle(body: VehicleIn, actor=Depends(auth.principal)):
    auth.require_role(actor, "owner")
    owner_id = body.owner_id if actor.get("service") else auth.identity(actor, body.owner_id)
    result = apply.create_vehicle({**body.model_dump(), "owner_id": owner_id})
    # Adding a vehicle can retry unrelated groups. Do not return their diffs.
    return result if actor.get("service") else {key: value for key, value in result.items() if key != "replans"}


@app.post("/vehicles/{vehicle_id}/cancel")
def cancel_vehicle(vehicle_id: int, actor=Depends(auth.principal)):
    auth.own_vehicle(actor, vehicle_id)
    result = apply.cancel_vehicle(vehicle_id)
    return result if actor.get("service") else {"vehicle_id": vehicle_id, "ok": True}


@app.post("/bookings/{booking_id}/approve")
def approve_booking(booking_id: int, actor=Depends(auth.principal)):
    auth.own_booking(actor, booking_id)
    return apply.approve_booking(booking_id)


@app.post("/bookings/{booking_id}/decline")
def decline_booking(booking_id: int, actor=Depends(auth.principal)):
    auth.own_booking(actor, booking_id)
    result = apply.decline_booking(booking_id)
    return result if actor.get("service") else {"booking": result["booking"]}


@app.post("/planner/run")
def planner_run(body: PlannerRunIn, actor=Depends(auth.require_service)):
    return apply.run_planning("manual_plan" if body.plan is not None else "api", body.trip_id,
                              match_id=body.match_id, mode=body.mode, dry_run=body.dry_run, plan=body.plan)


@app.get("/impact")
def impact():
    """Public: campus-wide projected totals, no personal data."""
    return apply.impact_summary()


@app.get("/events")
def events(since: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000), actor=Depends(auth.require_service)):
    return apply.events(since, limit)


@app.get("/agent-runs")
def agent_runs(limit: int = Query(50, ge=1, le=500), actor=Depends(auth.require_service)):
    return apply.agent_runs(limit)


@app.post("/trips/{trip_id}/plan")
def retry_trip_plan(trip_id: int, actor=Depends(auth.principal)):
    auth.own_trip(actor, trip_id)
    matches = apply.matches_for_trip(trip_id)
    apply.run_planning("traveler_retry", trip_id, match_id=matches[0]["id"] if matches else None)
    return {"matches": apply.matches_for_trip(trip_id)}


@app.get("/buyer/dataset")
def buyer_dataset(actor=Depends(auth.require_user)):
    auth.require_role(actor, "buyer")
    return apply.buyer_dataset()


@app.get("/buyer/insights")
def buyer_insights(actor=Depends(auth.require_user)):
    """Buyer-only model outputs. Same auth as /buyer/dataset."""
    auth.require_role(actor, "buyer")
    return apply.buyer_insights()


@app.get("/voice/agent")
def voice_agent():
    """Public: how the web page reaches the voice agent (widget agent id, phone number). Empty = not set up."""
    return {"agent_id": config.ELEVENLABS_AGENT_ID, "phone": config.TWILIO_PHONE_NUMBER}


app.mount("/", service_only(voice.mcp_app))   # last, so every route above wins; the voice agent's MCP endpoint at POST /mcp
