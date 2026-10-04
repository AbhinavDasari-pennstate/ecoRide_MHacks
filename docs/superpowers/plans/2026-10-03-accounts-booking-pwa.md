# Accounts, booking, and PWA implementation plan

**Goal:** Connect ERIDE around a public Book a trip landing page, real email/password accounts, personal booking and owner interfaces, approved buyer access, and installation as a PWA.

**Architecture:** Keep React/TanStack Start and FastAPI/Postgres. The server owns identity, role checks, sessions, and all bookings. The browser uses same-origin cookie-authenticated API requests. Public offline assets are the only service-worker cache contents.

**Accepted design:** The user requested connected interfaces, restricted accounts, a PWA, and a sustainable ride-sharing home page leading into booking. The user selected email/password signup. Riders book; owners list cars and approve only their own requests; approved buyers use the data portal. A new account does not get buyer privileges through signup.

## Shared constraints

- Preserve the existing simulated buyer dashboard and white/olive visual design.
- Never impersonate other participants or create shared demo identities during normal use.
- Passwords are salted and hashed; opaque sessions are HttpOnly cookies backed by hashed tokens in Postgres.
- Every personal API operation checks the session identity and ownership. Service access fails closed without an explicit configured token.
- The browser proxy must not inject the service token.
- Booking and account changes require a connection; offline mode never queues bookings or stores personal responses.
- Apply additive database migrations only. Use an isolated local database for verification.

## Tasks

1. Backend: add credentials/sessions/rate limits migration and auth routes; enforce authorization in main.py; add an existing-account buyer grant command and protected sample dataset endpoint. Verify real database signup, login, revocation, wrong-user requests, forged roles, and origin checks.
2. Booking and owner pages: replace guided impersonation with real forms; use current-account dashboards, passenger membership matching, self acceptance, and owner-only vehicle and booking actions. Verify submitted identity, form inputs, pending states, and permission-specific controls.
3. App integration: add session API helper, signup/login, public home, guarded navigation, personal profile, protected buyer data fetch, and remove proxy service credential injection. Verify guest redirects, role boundaries, session cleanup, and public landing availability when backend is down.
4. PWA: add manifest and icons, install controls, an offline fallback, and a public-assets-only service worker. Verify API/POST bypass and navigation fallback.
5. Integration: run frontend tests/type checks/build, backend suite, browser signup/login/booking/owner/buyer checks, and mobile/PWA inspection. Document startup, buyer approval, HTTPS deployment requirements, and remaining account lifecycle limits.

## Review focus

- A copied trip, match, owner, or booking ID cannot cross accounts.
- Signout clears personal UI and cached query data.
- A waiting trip is not shown as confirmed or free.
- Existing buyer data does not load before approved account access.
- Private pages and API payloads are never saved in the PWA cache.
