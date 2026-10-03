"""HTTP layer: thin routes over app.apply. Run with `uvicorn app.main:app` from the backend root.
LookupError -> 404, ValueError -> 422. Planning after POST /trips runs as a background task;
the other state changes replan synchronously inside apply and return the diff."""
from datetime import datetime
from contextlib import asynccontextmanager
import secrets
from typing import Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
import psycopg
from psycopg_pool import PoolTimeout

from app import apply, config, db


def service_access(request: Request, authorization: Optional[str] = Header(default=None)):
    if request.url.path == "/health":
        return
    if config.API_SERVICE_TOKEN and not secrets.compare_digest(
        (authorization or "").encode(), f"Bearer {config.API_SERVICE_TOKEN}".encode()
    ):
        raise HTTPException(401, "Valid service bearer token required", headers={"WWW-Authenticate": "Bearer"})


@asynccontextmanager
async def lifespan(app):
    yield
    db.close_pool()


app = FastAPI(title="Campus Rides", lifespan=lifespan, dependencies=[Depends(service_access)])
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


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
    user_id: int


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
            "gemini": "configured" if config.GEMINI_API_KEY else "missing"}


@app.get("/ready")
def ready():
    with db.conn() as c:
        if not c.execute("select to_regclass('schema_migrations') as name").fetchone()["name"]:
            raise HTTPException(503, "Database schema missing; run scripts/migrate.py")
        applied = {r["name"] for r in c.execute("select name from schema_migrations")}
        if any(p.name not in applied for p in db.MIGRATIONS.glob("*.sql")):
            raise HTTPException(503, "Database migrations pending; run scripts/migrate.py")
    return {"ok": True, "database": "connected"}


@app.post("/users")
def create_user(body: UserIn):
    return apply.create_user(body.model_dump())


@app.post("/users/{user_id}/identities")
def link_identity(user_id: int, body: IdentityIn):
    return apply.link_identity(user_id, body.provider, body.subject)


@app.get("/users/{user_id}/dashboard")
def dashboard(user_id: int):
    return apply.dashboard(user_id)


@app.get("/vehicles")
def vehicles(owner_id: Optional[int] = None, active: Optional[bool] = True,
             limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return apply.list_vehicles(owner_id, active, limit, offset)


@app.post("/trips")
def create_trip(body: TripIn, tasks: BackgroundTasks):
    trip = apply.create_trip(body.model_dump())
    tasks.add_task(apply.run_planning, "trip_created", trip["id"])
    return {"trip": trip, "planning": "queued"}


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
                              match_id=body.match_id, mode=body.mode, dry_run=body.dry_run, plan=body.plan)


@app.get("/impact")
def impact():
    return apply.impact_summary()


@app.get("/events")
def events(since: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
    return apply.events(since, limit)


@app.get("/agent-runs")
def agent_runs(limit: int = Query(50, ge=1, le=500)):
    return apply.agent_runs(limit)
