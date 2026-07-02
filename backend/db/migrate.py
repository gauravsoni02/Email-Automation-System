"""Apply the database schema.

Run from repo root:  python -m backend.db.migrate
Requires DATABASE_URL (hosted Postgres with the pgvector extension available).
"""

from __future__ import annotations

from pathlib import Path

from backend.adapters.db.database import get_connection

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def migrate() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("Schema applied successfully.")

    # LangGraph checkpointer tables (Phase 5) — separate connection/config.
    try:
        from backend.agents.checkpointer import setup_checkpointer

        setup_checkpointer()
        print("Checkpointer tables applied successfully.")
    except Exception as exc:  # noqa: BLE001
        print(f"Checkpointer setup skipped/failed: {exc}")


if __name__ == "__main__":
    migrate()
