"""HTTP layer: thin routes over app.apply. Run with `uvicorn app.main:app` from the backend root.
LookupError -> 404, ValueError -> 422. Planning after POST /trips runs as a background task;
the other state changes replan synchronously inside apply and return the diff."""
from datetime import datetime
from typing import Literal, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import apply, config

app = FastAPI(title="Campus Rides")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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


class PlannerRunIn(BaseModel):
    trip_id: Optional[int] = None
    dry_run: bool = False
    plan: Optional[dict] = None   # manual plan (fixtures): skips the planner, still completed + validated
    mode: Optional[Literal["gemini", "deterministic"]] = None


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {"ok": True, "planner": config.PLANNER, "maps": "live" if config.MAPS_SERVER_KEY else "offline",
            "gemini": "configured" if config.GEMINI_API_KEY else "missing"}


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
