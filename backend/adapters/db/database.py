"""Postgres connection management (psycopg3 + a connection pool).

A single lazily-initialised pool is shared across the app. pgvector types are
registered on each connection so `vector` columns round-trip as Python lists.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from psycopg import Connection
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from backend.config import get_settings


class DatabaseNotConfigured(RuntimeError):
    pass


def _configure_connection(conn: Connection) -> None:
    # register_vector looks up the `vector` type OID, which only exists after the
    # extension is created (migration). Tolerate its absence so the very first
    # connection — the one migration uses to CREATE EXTENSION — can be opened.
    try:
        register_vector(conn)
    except Exception:  # noqa: BLE001 - pre-migration: extension not installed yet
        conn.rollback()


def _reset_connection(conn: Connection) -> None:
    # Restore default row factory on return so a per-cursor override can never
    # leak to the next borrower of a pooled connection.
    conn.row_factory = tuple_row


@lru_cache
def get_pool() -> ConnectionPool:
    settings = get_settings()
    if not settings.database_url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. Provide a hosted Postgres (Neon/Supabase) "
            "connection string in your .env."
        )
    pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        configure=_configure_connection,
        reset=_reset_connection,
        open=True,
    )
    return pool


@contextmanager
def get_connection() -> Iterator[Connection]:
    """Borrow a connection from the pool; commits on success, rolls back on error."""
    pool = get_pool()
    with pool.connection() as conn:
        yield conn
