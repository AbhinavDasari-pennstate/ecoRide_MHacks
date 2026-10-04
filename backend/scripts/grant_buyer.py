"""Grant dataset access to an existing, explicitly named email account.

Run locally as an operator: python scripts/grant_buyer.py buyer@example.com
No default password is created. The person signs up first and keeps their password.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db


def grant(email):
    with db.conn() as c:
        row = c.execute("update auth_accounts set role = 'buyer' where email = %s returning user_id",
                        (email.strip().lower(),)).fetchone()
        if not row:
            raise ValueError("No account exists with that email. Sign up first.")
        c.execute("delete from auth_sessions where user_id = %s", (row["user_id"],))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    args = parser.parse_args()
    try:
        grant(args.email)
        print("Buyer access granted. Sign in again to open the data portal.")
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    finally:
        db.close_pool()
