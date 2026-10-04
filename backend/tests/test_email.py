"""Confirmation email: off unless SMTP is fully configured, deduped like the texts, and written to
a local outbox when there is nowhere to send it."""
import sys
from pathlib import Path

import pytest

from app import apply, config, db, notify
from test_database import database, postgres, trip  # noqa: F401  (pytest fixtures)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import demo_accounts  # noqa: E402


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    path = tmp_path / "outbox.local.log"
    monkeypatch.setattr(config, "EMAIL_OUTBOX", str(path))
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM"):
        monkeypatch.setattr(config, key, "")
    return path


@pytest.fixture
def smtp(monkeypatch):
    """SMTP fully configured, with the transport captured instead of connected."""
    for key, value in {"SMTP_HOST": "smtp.example.test", "SMTP_PORT": "587",
                       "SMTP_USER": "demo@example.test", "SMTP_PASSWORD": "app-password",
                       "EMAIL_FROM": "ecoRide <demo@example.test>"}.items():
        monkeypatch.setattr(config, key, value)
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent.append({"host": host, "port": port})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent[-1]["starttls"] = True

        def login(self, user, password):
            sent[-1]["logged_in"] = True

        def send_message(self, message):
            sent[-1]["to"] = message["To"]
            sent[-1]["subject"] = message["Subject"]
            sent[-1]["body"] = message.get_content()
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    return sent


def confirmed(database):
    """Alex drives Maya and Jordan, everyone accepts, Sam approves."""
    demo_accounts.create()
    for user_id in (2, 3):
        trip(database, user_id, "passenger")
    driver = trip(database, 1)
    match = apply.get_match(apply.run_planning("test", driver["id"])["match_ids"][0])
    for user_id in (1, 2, 3):
        apply.accept(match["id"], user_id)
    return apply.approve_booking(match["booking"]["id"])["match"]


def emails():
    with db.conn() as c:
        return c.execute("select payload from events where kind = %s and payload->>'channel' = 'email'"
                         " order by id", (notify.LEDGER,)).fetchall()


def test_email_is_off_until_every_setting_is_present(monkeypatch):
    assert notify.email_configured() is False
    for key, value in {"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p"}.items():
        monkeypatch.setattr(config, key, value)
    assert notify.email_configured() is False, "a missing EMAIL_FROM must not count as configured"
    monkeypatch.setattr(config, "EMAIL_FROM", "me@example.test")
    assert notify.email_configured() is True


def test_an_unconfigured_mailer_writes_to_the_outbox(database, outbox):
    match = confirmed(database)
    assert match["status"] == "confirmed"
    written = outbox.read_text(encoding="utf-8")
    assert "Your ecoRide trip is confirmed." in written
    assert "alex@eride.demo" in written and "maya@eride.demo" in written
    assert [e["payload"]["delivered"] for e in emails()] == ["outbox"] * 3
    assert all(e["payload"]["notice"] == "confirmed" for e in emails())


def test_the_email_carries_the_same_fare_and_co2_as_the_app(database, outbox):
    match = confirmed(database)
    written = outbox.read_text(encoding="utf-8")
    assert f"${match['cost_per_person_cents'] / 100:.2f}" in written
    assert f"{match['impact']['kg_co2_avoided']:.2f} kg" in written
    assert match["summary"] in written
    assert "projected estimates, not measured emissions" in written
    assert "—" not in written, "no em dashes in user-facing text"


def test_each_rider_is_emailed_once_however_often_it_confirms(database, outbox):
    match = confirmed(database)
    for _ in range(3):
        apply.approve_booking(match["booking"]["id"])      # idempotent approval
        notify.match_state_changed(match["id"])
        notify.email_confirmation(match["id"])
    assert len(emails()) == 3, "one per rider, not one per attempt"
    assert outbox.read_text(encoding="utf-8").count("Subject: Your ecoRide trip is confirmed") == 3


def test_the_owner_is_not_emailed_only_the_travellers(database, outbox):
    confirmed(database)
    recipients = {e["payload"]["user_id"] for e in emails()}
    assert recipients == {1, 2, 3}, "Sam owns the car but is not travelling"


def test_a_rider_without_a_web_account_is_skipped(database, outbox):
    demo_accounts.create()
    with db.conn() as c:
        c.execute("delete from auth_accounts where user_id = 3")   # Jordan has no login
    for user_id in (2, 3):
        trip(database, user_id, "passenger")
    driver = trip(database, 1)
    match = apply.get_match(apply.run_planning("test", driver["id"])["match_ids"][0])
    for user_id in (1, 2, 3):
        apply.accept(match["id"], user_id)
    apply.approve_booking(match["booking"]["id"])
    assert {e["payload"]["user_id"] for e in emails()} == {1, 2}


def test_a_configured_mailer_sends_over_smtp(database, smtp, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EMAIL_OUTBOX", str(tmp_path / "unused.local.log"))
    confirmed(database)
    assert len(smtp) == 3
    assert {s["host"] for s in smtp} == {"smtp.example.test"} and {s["port"] for s in smtp} == {587}
    assert all(s.get("starttls") and s.get("logged_in") for s in smtp)
    assert sorted(s["to"] for s in smtp) == ["alex@eride.demo", "jordan@eride.demo", "maya@eride.demo"]
    assert all("confirmed" in s["body"] for s in smtp)
    assert [e["payload"]["delivered"] for e in emails()] == ["smtp"] * 3
    assert not (tmp_path / "unused.local.log").exists(), "nothing should reach the outbox"


def test_port_465_uses_implicit_tls(database, smtp, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SMTP_PORT", "465")
    monkeypatch.setattr(config, "EMAIL_OUTBOX", str(tmp_path / "unused.local.log"))
    notify.send_email("someone@example.test", "subject", "body")
    assert smtp[-1]["port"] == 465 and "starttls" not in smtp[-1]


def test_a_failed_send_leaves_no_ledger_row_so_it_can_retry(database, monkeypatch, outbox):
    def explode(to, subject, body):
        raise RuntimeError("smtp refused")
    monkeypatch.setattr(notify, "send_email", explode)
    confirmed(database)
    assert emails() == []


def test_a_mail_fault_never_breaks_the_ride(database, monkeypatch, outbox):
    def explode(*a, **k):
        raise RuntimeError("mailer on fire")
    monkeypatch.setattr(notify, "_email_audience", explode)
    match = confirmed(database)
    assert match["status"] == "confirmed"
    assert emails() == []
