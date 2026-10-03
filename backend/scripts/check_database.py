"""Verify configured PostgreSQL with the API scenario, without resetting app data.

Creates an isolated schema inside one transaction and rolls the entire test back.
Requires schema-creation privileges (use the direct migration connection).
    python scripts/check_database.py
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config, db
from scripts import run_scenario


def main():
    print("Testing pooled connection...")
    with db.conn() as pooled:
        assert pooled.execute("select 1 as ok").fetchone()["ok"] == 1
    db.close_pool()
    namespace = "smoke_" + uuid4().hex
    with psycopg.connect(db._url(direct=True), row_factory=dict_row, connect_timeout=15) as connection:
        try:
            connection.execute(sql.SQL("create schema {}").format(sql.Identifier(namespace)))
            connection.execute(sql.SQL("set local search_path to {}").format(sql.Identifier(namespace)))
            assert connection.execute("select current_schema() as name").fetchone()["name"] == namespace
            connection.execute(db.SCHEMA.read_text(encoding="utf-8"))
            for path in sorted(db.MIGRATIONS.glob("*.sql")):
                connection.execute(path.read_text(encoding="utf-8"))

            @contextmanager
            def scoped_connection():
                with connection.transaction():
                    yield connection
                    # The outer transaction will roll back, so explicitly validate
                    # deferred constraints at each simulated application commit.
                    connection.execute("set constraints all immediate")
                    connection.execute("set constraints all deferred")

            with ExitStack() as stack:
                stack.enter_context(patch.object(db, "conn", scoped_connection))
                stack.enter_context(patch.object(db, "apply_schema", lambda: []))
                for name, value in {"MAPS_SERVER_KEY": "", "GEMINI_API_KEY": "",
                                    "PLANNER": "deterministic", "EXPLAIN": "template"}.items():
                    stack.enter_context(patch.object(config, name, value))
                run_scenario.results.clear()
                run_scenario.run("deterministic", allow_remote_reset=True)
                if not run_scenario.results or not all(run_scenario.results):
                    raise AssertionError("Scenario checks failed")

            # Verify the remote database itself rejects overlap, beyond the pure validator.
            rejected = False
            try:
                with connection.transaction():
                    booking = connection.execute("select * from bookings where status = 'requested' limit 1").fetchone()
                    match = connection.execute("insert into matches(driver_trip_id, vehicle_id, depart_time)"
                        " select driver_trip_id, vehicle_id, depart_time from matches where id = %s returning id",
                        (booking["match_id"],)).fetchone()
                    connection.execute("insert into bookings(match_id, vehicle_id, start_ts, end_ts, hours, price_cents)"
                        " values (%s, %s, %s, %s, %s, %s)",
                        (match["id"], booking["vehicle_id"], booking["start_ts"], booking["end_ts"], booking["hours"], booking["price_cents"]))
                    connection.execute("set constraints all immediate")
            except psycopg.errors.ExclusionViolation:
                rejected = True
            assert rejected, "PostgreSQL must reject overlapping reservations"
            print(f"PASS: {len(run_scenario.results)} scenario checks and database overlap constraint")
        finally:
            connection.rollback()
            print("Test transaction rolled back; existing application data preserved.")
        assert connection.execute("select to_regnamespace(%s) as name", (namespace,)).fetchone()["name"] is None
        print("PASS: temporary test schema removed by rollback")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Connection errors can include connection parameters; do not echo credentials.
        print(f"Database verification failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
