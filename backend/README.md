# Campus Rides backend

Campus trip sharing: students post trips (passengers, or drivers who may need a borrowed car). The backend groups them,
picks the lowest-CO2 vehicle, computes route, price and CO2 impact, and replans when a car or a rider drops out.
Gemini decides who rides with whom and explains why. Code decides everything that has to be right: vehicle, pickup
order, every number, validation and all database writes.

FastAPI + Postgres (Neon in prod, embedded `pgserver` for offline dev) + Google Routes/Geocoding + Gemini.
It works fully offline with no keys: distances fall back to straight-line distance x `ROAD_FACTOR` and planning falls
back to the deterministic planner.

Start with [Neon setup and team handoff](NEON_SETUP.md) for local commands, account/key setup,
database guarantees, integration contracts, and the 24-hour split. Account access is described below.

## Setup

```sh
# From the repository root (PowerShell)
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
Copy-Item backend/.env.example backend/.env   # only if .env does not already exist
cd backend
```

`.env` (gitignored, never commit it, never paste keys into code or chat):

| key | value |
|---|---|
| `DATABASE_URL` | Neon **pooled** URL, or `local` for the embedded Postgres in `%LOCALAPPDATA%/campus-rides-pg` |
| `LOCAL_DATABASE_PATH` | Absolute embedded PostgreSQL directory. Give each checkout its own directory, such as `C:\Users\abhin\ecoRide_MHacks\.local\postgres`; use the same value for migration and server processes. |
| `DATABASE_URL_DIRECT` | Required direct (unpooled) URL for remote migrations. Leave empty with `local`. |
| `API_SERVICE_TOKEN` | Optional bearer token for trusted server adapters; empty disables adapter and demo endpoints. Never forward it from a browser proxy. |
| `CORS_ORIGINS` | Exact frontend origins allowed for credentialed CORS and browser writes; defaults include localhost/127.0.0.1 ports 5173 and 5174. Set the deployed frontend origin explicitly. |
| `SESSION_COOKIE_SECURE` | `false` only for local HTTP; set `true` for HTTPS deployments. |
| `GEMINI_API_KEY` | optional; a Google AI Studio key (new keys start with `AQ.`); empty = deterministic planner only |
| `MAPS_SERVER_KEY` | optional; needs **Routes API** and **Geocoding API** enabled; empty = estimates |
| `PLANNER` | `gemini` (default; deterministic fallback without a key) or `deterministic` |
| `EXPLAIN` | `template` (default) or `gemini` |
| `GEMINI_MODEL` | optional override, default `gemini-3.6-flash` (fast and available in an Oct 3 probe; 3.7/3.8 were overloaded) |
| `GEMINI_BACKUP_MODEL` | optional, default `gemini-3.5-flash-lite`; used when the main model returns 429/5xx |
| `GEMINI_THINKING_LEVEL` | optional, default `low` (3.x Flash defaults to slower `medium`; never `minimal`) |

## Run

```sh
../.venv/Scripts/python scripts/migrate.py        # schema + pending migrations; preserves data
../.venv/Scripts/python scripts/check_database.py # full deterministic scenario in a rolled-back test schema
../.venv/Scripts/python scripts/seed.py           # resets LOCAL demo data; remote reset requires --reset-demo-db
../.venv/Scripts/uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
../.venv/Scripts/python scripts/run_scenario.py   # resets demo data; both planners; --write-fixtures refreshes frontend examples
../.venv/Scripts/python -m pytest -q              # unit tests + isolated real PostgreSQL integration tests
```

To run this checkout independently from the other local app, set `DATABASE_URL=local` and
`LOCAL_DATABASE_PATH=C:\Users\abhin\ecoRide_MHacks\.local\postgres` in the environment of both the migration
and API process. Set the frontend's server-side `BACKEND_URL=http://127.0.0.1:8001`. Start the API from `backend`:

```powershell
../.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --proxy-headers --forwarded-allow-ips "127.0.0.1,::1"
```

Authentication limits use the client address supplied by ASGI. When proxying, the trusted edge must **overwrite**
`X-Forwarded-For` with its incoming socket's remote address, not forward or append a caller-supplied value; it must
also set `X-Forwarded-Proto` from the actual connection. The Vite proxy implements this locally. Uvicorn trusts
only the explicit loopback proxy peers above, so different remote clients receive separate IP quotas and direct
untrusted clients cannot evade limits with forged headers. For production, replace the allowed peers with the exact
ingress proxy addresses, ensure that ingress normalizes those headers, and restrict network access to the backend.
Never use `--forwarded-allow-ips "*"` on a backend clients can reach directly. Without a proxy use `--no-proxy-headers`.
People genuinely sharing one public IP still share the 30-attempt/15-minute IP limit; each email also has its own limit.

`run_scenario.py` reseeds the database and drives the API in-process: Maya, Jordan and Alex request rides to Meijer,
get grouped into the Tesla (lowest CO2, even though the Civic is closer and cheaper), accept, Sam approves the booking,
the Tesla gets cancelled and the match moves to the Leaf, awaiting new traveler acceptance and owner approval. It also posts the fixture plans in
`fixtures/` to the validator. It prints PASS/FAIL per check and exits non-zero on any failure. `--write-fixtures`
writes real responses to `fixtures/api/*.json` for the frontend.

## API

All bodies and responses are JSON. Times are ISO 8601 (a naive time means America/Detroit). Money is integer cents.
Unknown id -> 404, bad input -> 422.

Browser accounts use the `eride_session` HttpOnly, SameSite=Lax cookie. Passwords use independently salted
scrypt (`N=2^17`, `r=8`, `p=1`); only SHA-256 hashes of opaque session tokens are stored. Sessions expire after
seven days and logout revokes the token. Authentication attempts are limited in PostgreSQL by normalized email
and client address. The server rejects browser writes from origins outside `CORS_ORIGINS` and marks API responses
`Cache-Control: no-store`. Use same-origin `/api` proxying in production and HTTPS with `SESSION_COOKIE_SECURE=true`.

| method | path | account behavior |
|---|---|---|
| POST | `/auth/signup` | `{name,email,password,role}`; role is `rider` or `owner`, password is 12–128 characters with spaces preserved. Returns 201 `{user}` and sets the cookie. Duplicate email returns 409. |
| POST | `/auth/login` | `{email,password}`; returns `{user}` and a new cookie. Invalid credentials return a generic 401. |
| GET | `/auth/me` | `{user}` or `{user:null}` if signed out/expired. User contains only `id`, `name`, `email`, `role`. |
| POST | `/auth/logout` | Revokes the current session, clears the cookie, returns `{ok:true}`. |
| GET | `/me/dashboard` | Current account's profile, trips, vehicles and authorized matches. |
| POST | `/trips/{id}/plan` | Retries planning for the current account's trip; returns only that trip's `{matches}`. |
| GET | `/buyer/dataset` | Buyer-only simulated dataset. Rider and owner accounts receive 403. |

Riders can book and manage their own trips. Owners can also book and manage their own vehicle listings and
booking requests. Match details are visible only to participating travelers and the selected vehicle's owner;
only the driver can choose a different vehicle. User/owner IDs supplied in browser bodies must match the session.
Listing vehicles from a browser returns only the current owner's vehicles; riders receive an empty list.

Buyer access is an operator grant, never an option a signup request can assign itself. After the person signs up,
run `python scripts/grant_buyer.py person@example.com` from `backend` using the intended database configuration.
This changes that account to buyer and revokes its existing sessions; the person signs in again with their own password.
No default accounts or passwords are created. Email delivery, email verification and password reset are not implemented.

The `/demo/*`, `/users` creation, identity-linking, `/planner/run`, `/events`, `/agent-runs`, and `/ready` endpoints
require an explicitly configured service bearer token. A blank token never bypasses authentication. Trusted scripts
may use this token on other operations, but a browser session always takes precedence and cannot inherit its privilege.

| method | path | what it does |
|---|---|---|
| GET | `/health` | `{ok, planner, maps: live\|offline, gemini: configured\|missing}` |
| GET | `/ready` | Database connectivity and pending migration check; 503 if unavailable or not migrated |
| POST | `/users` | Trusted adapter only: idempotent profile creation by `{provider, subject, name, roles, home_lat, home_lng, phone?}` |
| POST | `/users/{id}/identities` | Trusted adapter links a verified `{provider, subject}` to an existing account |
| GET | `/users/{id}/dashboard` | Consistent snapshot of profile, trips, listings, and participant/owner matches |
| GET | `/vehicles` | Filter by `owner_id`, `active`, `limit`, and `offset` |
| POST | `/trips` | create a trip `{user_id, role, dest_name, window_start, window_end, ...}`; planning runs in the background |
| PATCH | `/trips/{id}` | change a trip, then replan it (or its match) |
| POST | `/trips/{id}/cancel` | cancel a trip and replan its match (cause `trip_cancelled`) |
| GET | `/trips/{id}/matches` | the trip's live matches, newest first |
| GET | `/matches/{id}` | match: members, vehicle, booking, route (polyline + stops), pricing, impact, reasons, explanation, assumptions, last_change |
| POST | `/matches/{id}/accept` | `{user_id}` accepts; the match confirms once everyone accepted and the booking is approved |
| POST | `/vehicles` | add a vehicle (seats include the driver; efficiency is kWh/mi for EVs, mpg for gas); retries every `at_risk` match |
| POST | `/vehicles/{id}/cancel` | deactivate it, cancel its bookings, replan each affected match; returns the diffs |
| POST | `/bookings/{id}/approve` | owner approves |
| POST | `/bookings/{id}/decline` | owner declines; the match replans without that car |
| POST | `/planner/run` | `{trip_id?, match_id?, plan?, dry_run?, mode?}`: plan, recover an at-risk match, or validate a manual plan |
| GET | `/impact` | Projected totals over proposed/confirmed matches; not measured completed-trip savings |
| GET | `/events?since=` | event log after id `since` (poll it for a live feed) |
| GET | `/agent-runs` | one row per planning run: planner, raw Gemini output, validator errors, retries, latency, fallback |

The fixture plans use `{DEPART}` / `{DEPART_BAD}` tokens; substitute a real time before posting them.

## How a plan is made

1. **Scope:** open trips near the new trip's destination with overlapping windows (for a replan, the match's members too).
2. **Draft:** Gemini returns groups (driver, passengers, depart time, rationale) as structured JSON. A 429/5xx is retried
   once by the SDK, then the next attempt uses `GEMINI_BACKUP_MODEL`. With no key, or after a timeout, a hard error or
   3 invalid drafts (20 s total), the deterministic planner drafts instead (`fallback_used`). With no driver trip in
   scope there is nothing to group, so Gemini is skipped and the run logs as `deterministic`.
3. **Complete:** code picks the pickup order and the vehicle.
4. **Validate:** seats, windows, detours, range, availability, double booking. Errors go back to Gemini for a retry.
5. **Apply:** code computes route, price and impact, then writes the matches, members, bookings and events in one transaction.

**Vehicle rule:** among feasible vehicles, the lowest kg CO2 for the whole trip (including the deadhead to the driver).
Vehicles within 0.1 kg of each other count as a tie, and the cheaper one wins. Constants and their sources are in
`app/config.py` and travel with every match as `assumptions`.

## Before the demo

- [ ] Re-check the constants in `app/config.py`, especially `GAS_USD_PER_GALLON` (a price snapshot).
- [ ] Put the keys in `.env`, then check `GET /health` shows `maps: live` and `gemini: configured`.
- [ ] Run `scripts/seed.py` with the Maps key set, which pre-warms `route_cache`. Then run `run_scenario.py --planner gemini`
      once and look at `/agent-runs` for latency, models and fallbacks. Many 503s or 429s on one model: point
      `GEMINI_MODEL` at another Flash model. Free-tier quotas are per model, so don't loop the gemini scenario before the demo.
      `error: ClientError 401 UNAUTHENTICATED` means Google rejected the key; generate a new one in AI Studio.
- [ ] Reseed right before going on stage, because the scenario leaves the database in its end state.
- [ ] Rotate any key that was ever pasted into chat, a screenshot or a commit.

Known limits (marked `ponytail:` in the code): single process, so run one uvicorn worker. A rider who arrives after a
match is proposed isn't added to it until that match replans. A planning run holds its database transaction (and the
advisory lock) through the Gemini call, so accepts and approvals queue behind it for up to ~20 s.

Browser login and per-user authorization are enforced by the API. Trusted adapters remain responsible for verifying
their external identities and inbound webhook signatures. Never expose the adapter token to browser clients.
ElevenLabs/Photon delivery and durable background job retries are not implemented. Events are persisted for trusted-adapter polling;
failed disruptions stay `at_risk` and can be retried with `POST /planner/run` and `match_id`.
