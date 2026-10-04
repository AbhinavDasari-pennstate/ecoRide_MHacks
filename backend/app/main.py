"""HTTP layer: thin routes over app.apply, plus the voice agent's MCP server at /mcp.
Run with `uvicorn app.main:app` from the backend root. LookupError -> 404, ValueError -> 422.
Planning after POST /trips runs as a background task (or inline with ?wait=true); the other state
changes replan synchronously inside apply and return the diff."""
import hmac
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import apply, config, voice


@asynccontextmanager
async def _lifespan(_):
    async with voice.mcp.session_manager.run():   # the mounted MCP app's lifespan doesn't run on its own
        yield


class TokenGate:
    """With API_TOKEN set, every route except /health and the docs needs `X-Api-Key: <token>` or
    `Authorization: Bearer <token>`. The voice webhooks need a public URL, so this is the lock on it."""
    OPEN = {"/health", "/docs", "/openapi.json"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and config.API_TOKEN and scope["method"] != "OPTIONS" and scope["path"] not in self.OPEN:
            h = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            token = h.get("x-api-key") or h.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(token.encode(), config.API_TOKEN.encode()):
                return await JSONResponse({"detail": "missing or wrong API token"}, status_code=401)(scope, receive, send)
        await self.app(scope, receive, send)


app = FastAPI(title="Campus Rides", lifespan=_lifespan)
app.add_middleware(TokenGate)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])   # outermost: 401s keep CORS headers


@app.exception_handler(LookupError)
def _not_found(request, e):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(ValueError)
def _bad_input(request, e):
    return JSONResponse({"detail": str(e)}, status_code=422)


# ---------------------------------------------------------------- request bodies (None = apply's default)

class TripIn(BaseModel):
    user_id: int
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


class TripPatch(BaseModel):
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


class VehicleIn(BaseModel):
    make_model: str
    fuel_type: Literal["ev", "gas"]
    seats: int                    # total occupants incl. driver
    range_mi: float
    efficiency: float             # kWh/mi (ev) or mpg (gas)
    price_per_hour_cents: int
    avail_start: datetime
    avail_end: datetime
    owner_id: Optional[int] = None
    lat: Optional[float] = None   # default: the owner's home
    lng: Optional[float] = None


class AcceptIn(BaseModel):
    user_id: int


class TextIn(BaseModel):
    match_id: Optional[int] = None   # default: the user's latest ride


class CallIn(BaseModel):
    reason: str                      # short phrase the agent opens with, e.g. "confirm your seat"


class PlannerRunIn(BaseModel):
    trip_id: Optional[int] = None
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


@app.post("/trips")
def create_trip(body: TripIn, tasks: BackgroundTasks, wait: bool = False):
    trip = apply.create_trip(body.model_dump())
    if wait:   # voice and chat clients want the answer in the same request
        apply.run_planning("trip_created", trip["id"])
        return {"trip": trip, "planning": "done", "matches": apply.matches_for_trip(trip["id"])}
    tasks.add_task(apply.run_planning, "trip_created", trip["id"])
    return {"trip": trip, "planning": "queued"}


@app.get("/users")
def find_user(phone: str):
    return apply.find_user(phone)


@app.get("/users/{user_id}/rides")
def user_rides(user_id: int):
    return apply.user_rides(user_id)


@app.post("/users/{user_id}/text")
def text_user(user_id: int, body: TextIn):
    return voice.text_ride(user_id, body.match_id)


@app.post("/users/{user_id}/call")
def call_user(user_id: int, body: CallIn):
    return voice.call_user(user_id, body.reason)


@app.patch("/trips/{trip_id}")
def update_trip(trip_id: int, body: TripPatch):
    return apply.update_trip(trip_id, body.model_dump(exclude_unset=True))


@app.post("/trips/{trip_id}/cancel")
def cancel_trip(trip_id: int):
    return apply.cancel_trip(trip_id)


@app.get("/trips/{trip_id}/matches")
def trip_matches(trip_id: int):
    return apply.matches_for_trip(trip_id)


@app.get("/matches/{match_id}")
def get_match(match_id: int):
    m = apply.get_match(match_id)
    if m is None:
        raise HTTPException(404, f"no match with id {match_id}")
    return m


@app.post("/matches/{match_id}/accept")
def accept(match_id: int, body: AcceptIn):
    return apply.accept(match_id, body.user_id)


@app.post("/vehicles")
def create_vehicle(body: VehicleIn):
    return apply.create_vehicle(body.model_dump())


@app.post("/vehicles/{vehicle_id}/cancel")
def cancel_vehicle(vehicle_id: int):
    return apply.cancel_vehicle(vehicle_id)


@app.post("/bookings/{booking_id}/approve")
def approve_booking(booking_id: int):
    return apply.approve_booking(booking_id)


@app.post("/bookings/{booking_id}/decline")
def decline_booking(booking_id: int):
    return apply.decline_booking(booking_id)


@app.post("/planner/run")
def planner_run(body: PlannerRunIn):
    return apply.run_planning("manual_plan" if body.plan is not None else "api", body.trip_id,
                              mode=body.mode, dry_run=body.dry_run, plan=body.plan)


@app.get("/impact")
def impact():
    return apply.impact_summary()


@app.get("/events")
def events(since: int = 0, limit: int = 200):
    return apply.events(since, min(limit, 1000))


@app.get("/agent-runs")
def agent_runs(limit: int = 50):
    return apply.agent_runs(min(limit, 500))


app.mount("/", voice.mcp_app)   # last, so every route above wins; serves the voice agent's MCP endpoint at POST /mcp
