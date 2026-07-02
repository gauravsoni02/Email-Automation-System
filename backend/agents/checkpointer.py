"""LangGraph Postgres checkpointer (Phase 5).

The reply agent interrupts before sending and must be resumable from a *different*
request (and even after a process restart), so its graph state is persisted to
Postgres — the same single source of truth as the rest of the app.

PostgresSaver needs a connection configured with autocommit=True and
row_factory=dict_row, so it gets its own small pool (separate from the app pool,
which uses tuple rows and transactions).
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from backend.adapters.db.database import DatabaseNotConfigured
from backend.config import get_settings


@lru_cache
def get_checkpointer() -> PostgresSaver:
    settings = get_settings()
    if not settings.database_url:
        raise DatabaseNotConfigured("DATABASE_URL required for the agent checkpointer.")
    pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=True,
    )
    saver = PostgresSaver(pool)
    return saver


def setup_checkpointer() -> None:
    """Create the checkpointer tables (idempotent). Run once at migration time."""
    get_checkpointer().setup()
