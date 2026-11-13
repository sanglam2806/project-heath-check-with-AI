"""
PostgreSQL connection layer.

Optional: the app runs fine with DATABASE_URL unset (everything stays on
in-memory/mock data, same as before). Once DATABASE_URL is set in
server/.env, this module provides a pooled connection and the one-time
schema setup (run via `python init_db.py`, not automatically on startup —
applying DDL to someone's database should be a deliberate action).
"""
import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool as pg_pool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_pool: pg_pool.SimpleConnectionPool | None = None


def is_configured() -> bool:
    return bool(DATABASE_URL)


def _get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to server/.env (see .env.example)."
        )
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
    return _pool


@contextmanager
def get_connection():
    """Borrow a connection from the pool. Commits on success, rolls back
    and re-raises on error, always returns the connection to the pool."""
    conn = _get_pool().getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _get_pool().putconn(conn)


def check_connection() -> bool:
    """Cheap connectivity probe for the /health endpoint. Never raises."""
    if not DATABASE_URL:
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False


def init_schema() -> None:
    """Run server/schema.sql against the configured database. Safe to run
    more than once — every statement in schema.sql uses IF NOT EXISTS."""
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
