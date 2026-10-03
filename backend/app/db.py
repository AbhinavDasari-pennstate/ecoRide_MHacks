"""Postgres access: one lazy connection pool, one transaction per `with conn() as c:`, plain SQL.
Never print or log the URLs (they hold credentials)."""
import json
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
LOCK_KEY = 7337   # pg_advisory_xact_lock key: serializes planning runs and state changes

_pool = None
_pool_lock = threading.Lock()


def _url(direct: bool = False) -> str:
    if config.DATABASE_URL == "local":
        import pgserver  # dev only (requirements-dev.txt)
        path = os.path.join(os.environ["LOCALAPPDATA"], "campus-rides-pg")
        return pgserver.get_server(path, cleanup_mode=None).get_uri()
    return config.DATABASE_URL_DIRECT if direct else config.DATABASE_URL


def pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            # prepare_threshold=None: Neon's pooled endpoint is PgBouncer in transaction mode,
            # where server-side prepared statements break. check: Neon drops idle connections.
            _pool = ConnectionPool(_url(), kwargs={"row_factory": dict_row, "prepare_threshold": None},
                                   check=ConnectionPool.check_connection, min_size=1, max_size=10, open=True)
    return _pool


def conn():
    """`with db.conn() as c:` -> one transaction: commit on success, rollback on exception."""
    return pool().connection()


def apply_schema() -> None:
    with psycopg.connect(_url(direct=True), autocommit=True) as c:
        c.execute(SCHEMA.read_text())


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
    c.execute("insert into events (kind, payload) values (%s, %s)", (kind, J(payload)))


def agent_run(c, *, trigger, planner, tool_calls, raw_output, validator_errors, retries, latency_ms, fallback_used) -> int:
    return c.execute(
        "insert into agent_runs (trigger, planner, tool_calls, raw_output, validator_errors, retries, latency_ms, fallback_used)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (trigger, planner, J(tool_calls), J(raw_output), J(validator_errors), retries, latency_ms, fallback_used),
    ).fetchone()["id"]
