"""Repositories over Postgres.

All SQL is parameterized (no string interpolation of user/email input) and every
read/write is scoped to a `user_id` so one user can never touch another's data.
Callers depend on these repositories, not raw SQL.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.adapters.db.database import get_connection
from backend.models.rows import QueuedAction, StoredEmail, TaskItem


class UserRepository:
    def upsert(self, user_id: str) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id) VALUES (%s)
                ON CONFLICT (id) DO UPDATE SET updated_at = now()
                """,
                (user_id,),
            )

    def set_token(self, user_id: str, encrypted_token: str) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, encrypted_token)
                VALUES (%s, %s)
                ON CONFLICT (id)
                DO UPDATE SET encrypted_token = EXCLUDED.encrypted_token,
                              updated_at = now()
                """,
                (user_id, encrypted_token),
            )

    def get_token(self, user_id: str) -> str | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT encrypted_token FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        return row[0] if row and row[0] else None

    def exists(self, user_id: str) -> bool:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        return row is not None

    def list_ids(self) -> list[str]:
        with get_connection() as conn:
            rows = conn.execute("SELECT id FROM users").fetchall()
        return [r[0] for r in rows]


class EmailRepository:
    def upsert_raw(self, email: StoredEmail) -> None:
        """Insert/refresh an email's raw fields (before triage). Preserves
        existing triage outputs on conflict."""
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO emails (
                    id, user_id, thread_id, sender, recipient, subject,
                    snippet, body, internal_date, unread
                ) VALUES (
                    %(id)s, %(user_id)s, %(thread_id)s, %(sender)s, %(recipient)s,
                    %(subject)s, %(snippet)s, %(body)s, %(internal_date)s, %(unread)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    unread = EXCLUDED.unread,
                    snippet = EXCLUDED.snippet
                """,
                email.model_dump(
                    include={
                        "id", "user_id", "thread_id", "sender", "recipient",
                        "subject", "snippet", "body", "internal_date", "unread",
                    }
                ),
            )

    def set_embedding(self, user_id: str, email_id: str, embedding: list[float]) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE emails SET embedding = %s WHERE id = %s AND user_id = %s",
                (embedding, email_id, user_id),
            )

    def set_triage(
        self,
        user_id: str,
        email_id: str,
        *,
        category: str | None,
        category_confidence: float | None,
        priority: int | None,
        priority_reason: str | None,
        summary_one_line: str | None,
        summary_detailed: str | None,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE emails SET
                    category = %s, category_confidence = %s,
                    priority = %s, priority_reason = %s,
                    summary_one_line = %s, summary_detailed = %s,
                    processed_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (
                    category, category_confidence, priority, priority_reason,
                    summary_one_line, summary_detailed, email_id, user_id,
                ),
            )

    def get(self, user_id: str, email_id: str) -> StoredEmail | None:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "SELECT * FROM emails WHERE id = %s AND user_id = %s",
                (email_id, user_id),
            ).fetchone()
        return StoredEmail(**row) if row else None

    def list_for_user(
        self, user_id: str, limit: int = 50, order_by_priority: bool = False
    ) -> list[StoredEmail]:
        order = "priority DESC NULLS LAST" if order_by_priority else "internal_date DESC NULLS LAST"
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                f"""
                SELECT id, user_id, thread_id, sender, recipient, subject,
                       snippet, body, internal_date, unread, category,
                       category_confidence, priority, priority_reason,
                       summary_one_line, summary_detailed, created_at, processed_at
                FROM emails
                WHERE user_id = %s
                ORDER BY {order}
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [StoredEmail(**r) for r in rows]


class TaskRepository:
    def add(self, task: TaskItem) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (user_id, email_id, description, due_date, status)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (task.user_id, task.email_id, task.description, task.due_date, task.status),
            )

    def delete_for_email(self, user_id: str, email_id: str) -> None:
        """Clear existing tasks for an email before re-extracting (idempotent)."""
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM tasks WHERE user_id = %s AND email_id = %s",
                (user_id, email_id),
            )

    def list_for_user(self, user_id: str, status: str = "open") -> list[TaskItem]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                "SELECT * FROM tasks WHERE user_id = %s AND status = %s ORDER BY created_at DESC",
                (user_id, status),
            ).fetchall()
        return [TaskItem(**r) for r in rows]


class ActionQueueRepository:
    """The safety gate persisted. Created now; exercised from Phase 4/5."""

    def enqueue(self, action: QueuedAction) -> int:
        with get_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO action_queue (
                    user_id, action_type, status, payload, thread_id,
                    related_email_id, graph_thread_id
                ) VALUES (%s, %s, 'pending', %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    action.user_id, action.action_type, Jsonb(action.payload),
                    action.thread_id, action.related_email_id, action.graph_thread_id,
                ),
            ).fetchone()
        return row[0]

    def update_payload(self, user_id: str, action_id: int, payload: dict) -> None:
        """Apply an edit to a still-pending action's payload."""
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE action_queue SET payload = %s, updated_at = now()
                WHERE id = %s AND user_id = %s AND status = 'pending'
                """,
                (Jsonb(payload), action_id, user_id),
            )

    def get(self, user_id: str, action_id: int) -> QueuedAction | None:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "SELECT * FROM action_queue WHERE id = %s AND user_id = %s",
                (action_id, user_id),
            ).fetchone()
        return QueuedAction(**row) if row else None

    def related_email_ids(self, user_id: str) -> set[str]:
        """All email ids that already have ANY action (pending/executed/etc.),
        so follow-up scans don't repeatedly re-draft the same nudge."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT related_email_id FROM action_queue "
                "WHERE user_id = %s AND related_email_id IS NOT NULL",
                (user_id,),
            ).fetchall()
        return {r[0] for r in rows}

    def list_pending(self, user_id: str) -> list[QueuedAction]:
        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                "SELECT * FROM action_queue WHERE user_id = %s AND status = 'pending' ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return [QueuedAction(**r) for r in rows]

    def claim_pending(self, user_id: str, action_id: int, new_status: str) -> bool:
        """Atomically transition a PENDING action to `new_status`.

        Returns True only if this call performed the transition — used to make
        approve/reject single-shot so two concurrent requests can't both send.
        """
        with get_connection() as conn:
            row = conn.execute(
                """
                UPDATE action_queue
                SET status = %s, updated_at = now(),
                    approved_at = CASE WHEN %s = 'approved' THEN now() ELSE approved_at END
                WHERE id = %s AND user_id = %s AND status = 'pending'
                RETURNING id
                """,
                (new_status, new_status, action_id, user_id),
            ).fetchone()
        return row is not None

    def set_status(
        self,
        user_id: str,
        action_id: int,
        status: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE action_queue SET
                    status = %s,
                    result = COALESCE(%s, result),
                    updated_at = now(),
                    approved_at = CASE WHEN %s = 'approved' THEN now() ELSE approved_at END,
                    executed_at = CASE WHEN %s = 'executed' THEN now() ELSE executed_at END
                WHERE id = %s AND user_id = %s
                """,
                (
                    status, Jsonb(result) if result is not None else None,
                    status, status, action_id, user_id,
                ),
            )
