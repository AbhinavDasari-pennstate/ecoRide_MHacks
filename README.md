# ERIDE

A campus ride-sharing app with email/password accounts, shared-trip booking, an owner workspace, and an approved-buyer data portal.

## Start locally (Windows)

Install dependencies once, using Python 3.11+ and Node 22.12+:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd eride-repo
npm.cmd exec --yes --package=bun -- bun install --frozen-lockfile
cd ..
```

Backend terminal, from the repository root:

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
$env:DATABASE_URL='local'
$env:LOCAL_DATABASE_PATH=Join-Path (Get-Location) '.local\postgres'
cd backend
..\.venv\Scripts\python scripts/migrate.py
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --proxy-headers --forwarded-allow-ips '127.0.0.1,::1'
```

Frontend terminal, from the repository root:

```powershell
cd eride-repo
$env:BACKEND_URL='http://127.0.0.1:8001'
npm.cmd run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Open [ERIDE](http://127.0.0.1:5174). The isolated database lives in the ignored `.local/postgres` directory. API documentation is at [localhost:8001/docs](http://127.0.0.1:8001/docs).

## Accounts and booking

The home screen introduces shared travel and starts with **Book a trip**. Guests sign up or sign in, then return to booking. Passwords use scrypt hashing; sessions use revocable HttpOnly cookies. Authorization is enforced by the backend on every private route.

- **Rider:** request a trip, offer to drive a shared car, review matches and estimates, confirm or cancel their own place, and see their trips.
- **Car owner:** all rider features plus their own car listings, availability, and approval/decline of bookings for their vehicles.
- **Data buyer:** the protected Data Portal. Buyer access is assigned by an operator; it cannot be selected at signup.

To approve an existing buyer account, run in the backend terminal with the same database settings:

```powershell
..\.venv\Scripts\python scripts/grant_buyer.py buyer@example.com
```

They must sign in again after approval. No shared or hardcoded passwords are shipped. Email verification and password recovery are not yet implemented.

Booking has three steps: enter trip details, review a match, and confirm. Each traveler accepts their own place, and the selected car's owner approves the booking. Pages reload state from the database and poll for updates. No compatible driver/car means a clear waiting state. Current pickup and destination choices cover Ann Arbor campus routes. Prices and environmental impacts are estimates; the app does not process payments.

The buyer dataset is explicitly simulated: six drivers, 48 trips, one shared car. It is served by the buyer-only `/buyer/dataset` endpoint from `backend/fixtures/buyer_dataset.json`. Driver filters, event details, and JSON download work with that response. It is not a live telematics feed or a validated risk model.

## Installable app

ERIDE includes a manifest, app icons, an install prompt where supported, iPhone/iPad install guidance, and an offline page. Booking and account operations require an internet connection. The service worker caches only public offline assets; it never caches account API data or private pages.

For phone installation, deploy behind **HTTPS**. Route `/api/*` to FastAPI with the prefix removed, forward cookies, set `SESSION_COOKIE_SECURE=true`, and set `CORS_ORIGINS` to the exact frontend origin. The Vite proxy is for local development only. Configure a production reverse proxy to overwrite forwarded IP/protocol headers and trust only that proxy in Uvicorn. Do not forward a shared service token for browser requests. Keep `API_SERVICE_TOKEN`, database URLs, and API keys out of browser code and `VITE_*` settings.

## Checks

```powershell
# backend/
..\.venv\Scripts\python -m pytest -q

# eride-repo/
npm.cmd test
node node_modules/typescript/bin/tsc --noEmit
npm.cmd run build
```

Backend tests cover authenticated ownership, booking, session expiry/revocation, buyer access, and throttling. Frontend tests cover role guards, expired-session cleanup, booking states, portal filters, and offline cache boundaries.

See [backend setup](backend/README.md) for account/security details and [database setup](backend/NEON_SETUP.md) for Neon configuration.
