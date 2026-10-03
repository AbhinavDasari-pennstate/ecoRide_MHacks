"""Postgres access: one lazy connection pool, one transaction per `with conn() as c:`, plain SQL.
Never print or log the URLs (they hold credentials)."""
import json
import hashlib
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app import config

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
MIGRATIONS = SCHEMA.parent / "migrations"
LOCK_KEY = 7337   # pg_advisory_xact_lock key: serializes planning runs and state changes

_pool = None
_pool_lock = threading.Lock()


def _url(direct: bool = False) -> str:
    if config.DATABASE_URL == "local":
        import pgserver  # dev only (requirements-dev.txt)
        path = os.getenv("LOCAL_DATABASE_PATH") or str(Path(os.getenv("LOCALAPPDATA", Path.home() / ".local/share")) / "campus-rides-pg")
        return pgserver.get_server(path, cleanup_mode=None).get_uri()
    if direct and not config.DATABASE_URL_DIRECT:
        raise ValueError("Set DATABASE_URL_DIRECT to the direct Neon connection string before migrating")
    return config.DATABASE_URL_DIRECT if direct else config.DATABASE_URL


def pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            # Disable prepared statements for compatibility with pooled endpoints.
            # Check connections on checkout because Neon can suspend idle computes.
            _pool = ConnectionPool(_url(), kwargs={"row_factory": dict_row, "prepare_threshold": None},
                                   check=ConnectionPool.check_connection, min_size=0, max_size=10,
                                   timeout=10, open=True)
    return _pool


def conn():
    """`with db.conn() as c:` -> one transaction: commit on success, rollback on exception."""
    return pool().connection()


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def apply_schema() -> list[str]:
    """Bootstrap and upgrade atomically; never reset application data.

    The original schema is the baseline. Append numbered migrations; do not edit
    applied migrations. The checksums detect accidental changes on later deploys.
    """
    applied = []
    with psycopg.connect(_url(direct=True), connect_timeout=10) as c:
        lock(c)
        c.execute(SCHEMA.read_text(encoding="utf-8"))
        c.execute("create table if not exists schema_migrations (name text primary key,"
                  " checksum text not null, applied_at timestamptz not null default now())")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            row = c.execute("select checksum from schema_migrations where name = %s", (path.name,)).fetchone()
            if row:
                if row[0] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}; add a new migration instead")
                continue
            c.execute(sql)
            c.execute("insert into schema_migrations (name, checksum) values (%s, %s)", (path.name, checksum))
            applied.append(path.name)
    return applied


def lock(c) -> None:
    """Held until the transaction ends."""
    c.execute("select pg_advisory_xact_lock(%s)", (LOCK_KEY,))


def _default(o):
    if isinstance(o, datetime):
        return o.astimezone(timezone.utc).isoformat()
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def J(obj) -> Jsonb:
    """jsonb parameter; datetimes become ISO UTC strings."""
    return Jsonb(obj, dumps=lambda o: json.dumps(o, default=_default))


def event(c, kind: str, payload: dict) -> None:
    # Every event writer uses the same transaction lock: IDs become visible in
    # commit order, so a polling consumer cannot skip a late-committing lower ID.
    lock(c)
    c.execute("insert into events (kind, payload) values (%s, %s)", (kind, J(payload)))


def agent_run(c, *, trigger, planner, tool_calls, raw_output, validator_errors, retries, latency_ms, fallback_used) -> int:
    return c.execute(
        "insert into agent_runs (trigger, planner, tool_calls, raw_output, validator_errors, retries, latency_ms, fallback_used)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (trigger, planner, J(tool_calls), J(raw_output), J(validator_errors), retries, latency_ms, fallback_used),
    ).fetchone()["id"]
