# Database setup and team handoff

The app uses one PostgreSQL database for web, voice, and messaging. Local development runs real PostgreSQL via
`pgserver`; Neon uses the same SQL and Python code. The configured Neon database was verified on October 3, 2026:
pooled/direct TLS connections, migrations, all 28 deterministic API scenario checks, and overlap rejection passed.
Scenario data was isolated and rolled back; only the application schema/migrations were retained.

## Run locally (PowerShell)

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
cd backend
..\.venv\Scripts\python scripts/migrate.py
..\.venv\Scripts\python scripts/seed.py
..\.venv\Scripts\python scripts/run_scenario.py --planner deterministic
..\.venv\Scripts\python -m pytest -q
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`. `GET /health` checks the process; `GET /ready` checks the database and migrations.
The scenario resets demo data and leaves the Tesla cancelled and its replacement awaiting confirmations.
Run `scripts/seed.py` again for the demo's starting state. Local DB data lives outside the repository, under
`%LOCALAPPDATA%/campus-rides-pg`, unless `LOCAL_DATABASE_PATH` is set. Linux/macOS default to `~/.local/share/campus-rides-pg`.
Tests use an isolated temporary database for account, constraint, concurrency, and workflow checks.

## Accounts and keys: first 30 minutes, Person 1

| Account | Action | Configuration |
|---|---|---|
| [Neon](https://console.neon.tech) | Create a project and disposable development branch; copy both connection strings | `DATABASE_URL` pooled, `DATABASE_URL_DIRECT` direct |
| [Google AI Studio](https://aistudio.google.com/apikey) | Create a Gemini API key | `GEMINI_API_KEY`; existing default `gemini-3.6-flash`, backup `gemini-3.5-flash-lite` |
| [Google Cloud](https://console.cloud.google.com/apis/library) | Select a billing-enabled project; enable Routes and Geocoding APIs | `MAPS_SERVER_KEY`, restricted to these APIs and server IPs where practical |
| Google Cloud browser key | Enable Maps JavaScript API; restrict by HTTP referrers for localhost and deployed frontend | Frontend only; never reuse `MAPS_SERVER_KEY` |
| Backend service token | Generate a random secret for trusted web/voice/message server adapters | `API_SERVICE_TOKEN`; do not embed in browser JavaScript |

`.gitignore` already excludes `.env`, `.env.*` (except examples), virtual environments, and Python caches.
Store credentials in `backend/.env` locally and deployment secret settings remotely. Keep Neon's supplied TLS
parameters such as `sslmode=require`; never send the connection strings to the frontend.

### Switch to Neon

1. Set the two URLs in `backend/.env`. The pooled hostname contains `-pooler`; the direct one does not.
2. Set `API_SERVICE_TOKEN` for operator adapters, the deployed `CORS_ORIGINS`, `SESSION_COOKIE_SECURE=true`
   for HTTPS, and optional Gemini/Maps keys. Do not inject the adapter token into a browser proxy.
3. Run `python scripts/migrate.py` using the virtual environment. This preserves existing data.
4. Restart the API, then call `/ready` with `Authorization: Bearer <service token>`.
   Run `python scripts/check_database.py` to exercise the complete deterministic scenario in a temporary schema
   that is rolled back automatically. This verifies the connection and workflow without resetting application data.
5. On a **disposable demo branch only**, run `python scripts/seed.py --reset-demo-db` and then
   `python scripts/run_scenario.py --planner deterministic --reset-demo-db`.

Remote seeds are destructive and are blocked without the explicit reset flag. The direct URL is mandatory
for remote migrations; the app uses the pooled URL. [Neon connection guidance](https://neon.com/docs/connect/connect-from-any-app)
describes both endpoint types. `check_database.py` uses the direct endpoint for its isolated transaction;
it also verifies the app's pooled connection before running the scenario.

## Database contract

| Table | Purpose |
|---|---|
| `users`, `user_identities` | Profiles, roles, and verified external identifiers mapped to one account |
| `auth_accounts`, `auth_sessions`, `auth_rate_limits` | Email/password accounts, hashed cookie sessions, persistent authentication throttles |
| `vehicles` | Owner, location, availability, capacity, efficiency and source, rental price |
| `trips` | Driver/rider intent, destination, departure window, party size, lifecycle |
| `matches`, `match_members` | Group, route, participant acceptance, price and impact snapshots |
| `bookings` | Requested/approved reservations and historical cancellations/declines |
| `route_cache` | Reusable route data for the Google Maps adapter |
| `agent_runs`, `events` | Planner trace and append-only activity feed |
| `schema_migrations` | Applied migration filenames, checksums and timestamps |

`db/schema.sql` is the original bootstrap schema. `scripts/migrate.py` applies it and then numbered files in
`db/migrations/` atomically. Add a new numbered migration for later changes; modifying an applied migration
fails checksum verification. Existing rows that violate a new constraint cause migration rollback; they are
not silently deleted or changed. SQL values use parameters, timestamps use `timestamptz`, money uses integer cents.

PostgreSQL enforces non-overlapping requested/approved vehicle bookings with half-open `[start, end)` intervals.
Adjacent bookings are valid. Cancelled/declined reservations do not occupy the slot. Exclusion constraints
use built-in GiST range operators and need no extension. One trip can have only one active match membership;
the deferred constraint permits atomic transfers during replanning. Each match has at most one live booking.

Application writes share a transaction-level advisory lock, compatible with transaction pooling. Planning
validates and writes matches, memberships, bookings, computed values and events in one transaction. Events are
serialized before ID allocation so a polling consumer cannot skip a lower ID that commits later.

A cancelled car or changed trip marks its match `at_risk` before replanning. On failure, recover with
`POST /planner/run {"match_id": 1}`. Replacement bookings need owner approval. Changes to vehicle, departure,
pickup order or per-person price require traveler acceptance again. Confirmed means all live members accepted
and the current reservation is approved. Repeated acceptance/approval is idempotent.

## Frontend, voice and messaging contract

The existing fixture JSON in `fixtures/api/` provides the frontend's initial contract. Regenerate it with
`python scripts/run_scenario.py --planner deterministic --write-fixtures` on a local/demo database.
The Plan JSON models remain in `app/core.py`, with valid/invalid examples in `fixtures/`.

Browser accounts now use `/auth/signup`, `/auth/login`, `/auth/me` and `/auth/logout`, with an HttpOnly session
cookie and server-enforced ownership checks. See `README.md` for signup fields, role permissions and buyer grants.
The browser reads `/me/dashboard`; the raw event feed is restricted to trusted adapters.

For a profile verified through an external identity provider, a trusted adapter calls:

```json
{"provider":"web","subject":"verified-auth-user-id","name":"Alex","roles":["driver"],"home_lat":42.278,"home_lng":-83.740}
```

Send that to `POST /users`; retries return the same user by `(provider, subject)` without overwriting the profile.
Use `POST /users/{id}/identities` to attach a verified voice/message identifier to the same account. A claimed
phone number or caller-provided user ID is not identity verification. Display names are intentionally non-unique.

Trusted adapters read `GET /users/{id}/dashboard` for profile, trips, owned vehicles and matches and poll
`/events?since=<last_id>` for updates. Use the routes in `README.md` for trip creation, acceptance, cancellation
and owner approval. Webhook signature checking and Photon/ElevenLabs transport adapters still belong in the
integration layer. Texts and calls go out through `app/voice.py`; match notices sit behind `NOTIFY_ON_MATCH` and confirmation email behind the `SMTP_*` settings, both off until configured. A blank service token disables adapter access.
In-process background planning is suitable for the hackathon; it is not a durable queue and should use one API worker.

## Assumptions checked on October 3, 2026

Every match stores the assumption values, units, source labels and source URLs used for that calculation.

| Value | Snapshot and source |
|---|---|
| Gasoline emissions | 8.887 kg CO2/gal; [EPA typical passenger vehicle](https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle) |
| Baseline gasoline trip | 0.400 kg CO2/mi; same EPA source, assuming separate gasoline round trips |
| Michigan electricity | 0.440 kg CO2/kWh, rounded from RFCM 970.617 lb/MWh × 0.45359237 / 1000; [EPA eGRID2023 summary](https://www.epa.gov/egrid/summary-data) |
| Gas price | $4.48/gal, rounded from $4.4815 Michigan regular; [AAA, Oct 3](https://gasprices.aaa.com/?state=MI) |
| Electricity price | $0.2305/kWh, July 2026 Michigan residential; [EIA Table 5.6.A](https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a) |
| Tesla | 2026 Model 3 Standard RWD, 0.243 kWh/mi, 321 mi; [fueleconomy.gov 50251](https://www.fueleconomy.gov/ws/rest/vehicle/50251) |
| Civic | 2025 Civic 4Dr 2.0L CVT, 36 combined mpg; [fueleconomy.gov 48016](https://www.fueleconomy.gov/ws/rest/vehicle/48016) |
| RAV4 | 2025 RAV4 FWD 2.5L, 30 combined mpg; [fueleconomy.gov 48910](https://www.fueleconomy.gov/ws/rest/vehicle/48910) |
| Leaf | 2025 LEAF, 0.304 kWh/mi, 149 mi; [fueleconomy.gov 48400](https://www.fueleconomy.gov/ws/rest/vehicle/48400) |

EV consumption is rounded from `combE` (kWh/100 mi) divided by 100. Gas-car ranges, rental prices, trip duration
buffers and road-distance multipliers are demo assumptions. Grid emissions exclude transmission losses;
gas emissions are tailpipe-only. Neither includes vehicle manufacturing or full lifecycle effects.
Impact totals are projected savings for proposed/confirmed journeys, not measured completed travel.
Google's [model catalog](https://ai.google.dev/gemini-api/docs/models) lists the configured models as stable;
availability and latency still require a real-key integration check.

## 24-hour team split

| Hours | Person 1: Neon + API | Person 2: Gemini + core | Person 3: frontend |
|---|---|---|---|
| 0–1 | Freeze schema/migrations, Plan JSON and fixtures together | Same | Same |
| 1–6 | Add Neon keys, migrate demo branch, seed, check Maps/cache | Validate math, fallback and edge cases | Dashboard against fixtures, map and polyline |
| 6–12 | Account adapters, events, API integration | Real Gemini structured output, timeout/retry/fallback | Match, cost, impact and assumption panels |
| 12–16 | Pass deterministic scenario on Neon | Pass same scenario with Gemini | Wire live API through authenticated adapter |
| 16–20 | Cancellation/recovery, identity checks, impact | Demonstrate improved grouping over fallback | Activity feed; changed-fare/owner approvals |
| 20–24 | Freeze and rehearse | Verify constants, remove flaky paths | Rehearse voice/message handoffs |

Hard gate: by hour 16, the deterministic scenario passes. Stop adding features until it does.
