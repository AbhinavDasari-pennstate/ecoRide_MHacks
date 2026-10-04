"""Give the seeded demo people web logins, so the same person can be on the phone and on a screen.

The accounts attach to the existing seeded users (Alex is still user 1, the number in DEMO_PHONES
still finds him), rather than signing up new duplicates. Idempotent: safe to rerun, and safe to run
again after seed.reset(), which truncates auth_accounts along with users.

    python scripts/demo_accounts.py

Writes the credentials to backend/DEMO_LOGINS.local.txt, which .gitignore excludes.
Demo passwords only. Never use these on anything real.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth, config, db  # noqa: E402

LOGINS = Path(__file__).resolve().parents[1] / "DEMO_LOGINS.local.txt"
FRONTEND_URL = os.getenv("DEMO_FRONTEND_URL", "http://localhost:5173")

# (seeded user id or None to create a standalone account, name, email, password, web role)
# Passwords are 12+ characters so they also satisfy the signup form's rules.
ACCOUNTS = [
    (1, "Alex", "alex@eride.demo", "demo-alex-2026", "rider"),
    (2, "Maya", "maya@eride.demo", "demo-maya-2026", "rider"),
    (3, "Jordan", "jordan@eride.demo", "demo-jordan-2026", "rider"),
    (4, "Sam", "sam@eride.demo", "demo-sam-2026", "owner"),
    (None, "Dana", "buyer@eride.demo", "demo-buyer-2026", "buyer"),
]


def _standalone(c, name: str, email: str) -> int:
    """A person who is not part of the ride scenario (the data buyer). Keyed by identity, not name,
    because display names are deliberately not unique."""
    row = c.execute("select u.id from users u join user_identities i on i.user_id = u.id"
                    " where i.provider = 'eride-demo-login' and i.subject = %s", (email,)).fetchone()
    if row:
        return row["id"]
    row = c.execute("insert into users (name, roles, home_lat, home_lng, verified)"
                    " values (%s, '{}', %s, %s, true) returning id", (name, *config.ANN_ARBOR)).fetchone()
    c.execute("insert into user_identities (provider, subject, user_id) values ('eride-demo-login', %s, %s)",
              (email, row["id"]))
    return row["id"]


def ensure(c, user_id, name, email, password, role) -> int:
    if user_id is None:
        user_id = _standalone(c, name, email)
    elif not c.execute("select 1 from users where id = %s", (user_id,)).fetchone():
        raise LookupError(f"seeded user {user_id} ({name}) is missing. Run scripts/seed.py first.")
    # An earlier run may have parked this email on a different row; email is unique.
    c.execute("delete from auth_accounts where email = %s and user_id <> %s", (email, user_id))
    c.execute("insert into auth_accounts (user_id, email, password_hash, role) values (%s, %s, %s, %s)"
              " on conflict (user_id) do update set email = excluded.email,"
              " password_hash = excluded.password_hash, role = excluded.role",
              (user_id, email, auth._hash_password(password), role))
    # Cookies from before a reset would point at trips that no longer exist.
    c.execute("delete from auth_sessions where user_id = %s", (user_id,))
    return user_id


def create() -> list[dict]:
    out = []
    with db.conn() as c:
        db.lock(c)
        for user_id, name, email, password, role in ACCOUNTS:
            resolved = ensure(c, user_id, name, email, password, role)
            out.append({"user_id": resolved, "name": name, "email": email,
                        "password": password, "role": role})
    return out


def write_file(accounts: list[dict]) -> Path:
    lines = ["eCARide demo logins (local only, gitignored, demo passwords)",
             f"Sign in at {FRONTEND_URL}/login", ""]
    lines += [f"{a['name']:<8} user {a['user_id']:<3} {a['role']:<6} {a['email']:<20} {a['password']}"
              for a in accounts]
    lines += ["", "Alex is the seeded caller: the DEMO_PHONES number reaches this same account,",
              "so a booking made on the phone shows up on Alex's screen."]
    LOGINS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return LOGINS


def report(accounts: list[dict]) -> None:
    print("\n  demo logins")
    for a in accounts:
        print(f"    {a['name']:<8} user {a['user_id']:<3} {a['role']:<6} {a['email']:<20} {a['password']}")
    print(f"\n  sign in at {FRONTEND_URL}/login")
    print(f"  also written to {LOGINS.name} (gitignored)")


if __name__ == "__main__":
    try:
        accounts = create()
        write_file(accounts)
        report(accounts)
    finally:
        db.close_pool()
