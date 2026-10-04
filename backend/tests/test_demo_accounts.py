"""The demo logins must attach to the seeded people, not create duplicates of them, and must
survive a reset so one command puts the stage back."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app import config, db
from app.main import app
from scripts import seed
from test_database import database, postgres  # noqa: F401  (pytest fixtures)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import demo_accounts  # noqa: E402


def users_named(name):
    with db.conn() as c:
        return [r["id"] for r in c.execute("select id from users where name = %s order by id", (name,))]


def test_logins_attach_to_the_seeded_people(database):
    accounts = demo_accounts.create()
    by_name = {a["name"]: a for a in accounts}
    assert by_name["Alex"]["user_id"] == 1 and by_name["Maya"]["user_id"] == 2
    assert by_name["Jordan"]["user_id"] == 3 and by_name["Sam"]["user_id"] == 4
    assert by_name["Sam"]["role"] == "owner" and by_name["Alex"]["role"] == "rider"
    # Alex is still the one seed.py gave the DEMO_PHONES number to, so a call reaches this account.
    assert users_named("Alex") == [1]
    with db.conn() as c:
        assert c.execute("select owner_id from vehicles where make_model = 'Tesla Model 3'").fetchone()[
            "owner_id"] == by_name["Sam"]["user_id"]


def test_rerunning_changes_nothing(database):
    first = demo_accounts.create()
    with db.conn() as c:
        before = c.execute("select count(*) as n from users").fetchone()["n"]
    second = demo_accounts.create()
    with db.conn() as c:
        after = c.execute("select count(*) as n from users").fetchone()["n"]
        logins = c.execute("select count(*) as n from auth_accounts").fetchone()["n"]
    assert [a["user_id"] for a in first] == [a["user_id"] for a in second]
    assert before == after and logins == len(demo_accounts.ACCOUNTS)


def test_the_logins_come_back_after_a_reset(database):
    first = demo_accounts.create()
    seed.reset()                       # truncates users with cascade, so the logins go too
    with db.conn() as c:
        assert c.execute("select count(*) as n from auth_accounts").fetchone()["n"] == 0
    second = demo_accounts.create()
    assert [a["user_id"] for a in second if a["name"] != "Dana"] == [
        a["user_id"] for a in first if a["name"] != "Dana"]
    with db.conn() as c:
        assert c.execute("select count(*) as n from auth_accounts").fetchone()["n"] == len(demo_accounts.ACCOUNTS)


def test_a_reset_revokes_old_cookies(database):
    demo_accounts.create()
    with TestClient(app) as client:
        signed_in = client.post("/auth/login", json={"email": "alex@eride.demo", "password": "demo-alex-2026"})
        assert signed_in.status_code == 200
        assert client.get("/auth/me").json()["user"]["id"] == 1
        demo_accounts.create()         # a fresh demo reset
        assert client.get("/auth/me").json() == {"user": None}


def test_every_demo_login_works_and_lands_on_the_right_data(database):
    demo_accounts.create()
    for _, name, email, password, role in demo_accounts.ACCOUNTS:
        with TestClient(app) as client:
            assert client.post("/auth/login", json={"email": email, "password": password}).status_code == 200
            me = client.get("/auth/me").json()["user"]
            assert (me["name"], me["role"]) == (name, role)
            board = client.get("/me/dashboard")
            if role == "buyer":
                assert client.get("/buyer/dataset").status_code == 200
                assert board.status_code == 200 and board.json()["trips"] == []
            else:
                assert client.get("/buyer/dataset").status_code == 403
                assert board.status_code == 200
            if name == "Sam":
                assert [v["make_model"] for v in board.json()["vehicles"]] == ["Tesla Model 3"]


def test_the_buyer_never_takes_part_in_planning(database):
    accounts = demo_accounts.create()
    dana = next(a for a in accounts if a["name"] == "Dana")
    with db.conn() as c:
        row = c.execute("select roles from users where id = %s", (dana["user_id"],)).fetchone()
    assert row["roles"] == []          # no driver, passenger or owner role, so no match can include them


def test_a_missing_seed_is_reported_rather_than_guessed(database, monkeypatch):
    with db.conn() as c:
        c.execute("delete from auth_accounts")
        c.execute("delete from user_identities")
        c.execute("delete from trips")
        c.execute("delete from vehicles")
        c.execute("delete from users where id = 4")
    import pytest
    with pytest.raises(LookupError, match="seeded user 4"):
        demo_accounts.create()
    assert config.TIMEZONE                # config import is exercised by the script too
