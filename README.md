# ERIDE

The React app in `eride-repo/` uses the FastAPI backend in `backend/` and its configured PostgreSQL database
(Neon or local). Trip state, prices, emissions, confirmations, bookings and activity come from the backend.

## Run locally on Windows

From this repository, use two PowerShell terminals. Dependencies are already installed in the current checkout.

**Backend**

```powershell
cd backend
..\.venv\Scripts\python scripts/migrate.py
..\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend**

```powershell
cd eride-repo
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Open **http://localhost:5173**. API documentation is at **http://localhost:8000/docs**.
If a port is already in use, use the existing server or stop it before starting another.

For a fresh checkout, install dependencies first:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
cd eride-repo
npm.cmd exec --yes --package=bun -- bun install --frozen-lockfile
```

Keep database URLs and API keys in `backend/.env`. The Vite development server proxies `/api/*` to
`http://127.0.0.1:8000`, forwarding `API_SERVICE_TOKEN` from the backend environment on the server only.
No database credentials or service tokens belong in `VITE_*` settings or browser code.
To use a different backend locally, set the frontend server's `BACKEND_URL` environment variable.

## Connected demo

Opening the app provisions seven explicitly identified demo accounts and four cars if missing. It does not
truncate the database or replace existing application records. Starting the guided trip creates real requests
for Alex, Maya and Jordan. The planner selects a feasible group and car, and the UI displays its actual results.

- Accept separately for each traveler, then approve as the current vehicle owner.
- Choosing another vehicle or cancelling the current one recalculates the plan and requires new confirmations.
- Reloading any page restores the trip, booking, prices and impact from the database.
- The profile activity feed polls persisted events. Messages are presentation bubbles reconstructed by the guided steps.
- **Restart demo** (or Shift+R) cancels requests belonging to the demo identities and restores their vehicle availability.
  It retains historical rows and events. All browser tabs share this same demonstration scenario.

The voice transcript and phone panels are explicitly labeled simulations. Their actions make real API calls;
they do not send actual iMessages or use live speech recognition. The map shows the backend's pickup stops as a
schematic. Missing Maps/Gemini keys use estimated routes and the deterministic planner.

The role-switching controls are for this local hackathon demo, not user authentication. Before a public deployment,
add authenticated per-user authorization and gate demo controls. The production frontend needs an authenticated
reverse proxy for `/api` (the Vite proxy is development-only), or an appropriately secured `VITE_API_BASE_URL`.

## Checks

```powershell
# From backend/
..\.venv\Scripts\python -m pytest -q

# From eride-repo/
npm.cmd test
node node_modules/typescript/bin/tsc --noEmit
npm.cmd run build

# Optional integration check against both running servers; writes to demo accounts only
$env:LIVE_API_URL='http://localhost:5173'
npm.cmd test
Remove-Item Env:LIVE_API_URL
```

The live test creates a trip, accepts travelers, approves the owner, restores data from the dashboard,
cancels the vehicle and confirms the replacement. It leaves a confirmed replacement trip available to inspect.
Use **Restart demo** for a fresh presentation.

See [backend setup](backend/NEON_SETUP.md) for Neon provisioning and the database contract.
