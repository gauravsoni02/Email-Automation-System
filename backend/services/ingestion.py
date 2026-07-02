"""Ingestion pipeline: fetch -> store -> embed -> run triage processors.

Runs as a FastAPI background task (POST /ingest). For each email:
  1. read full message (Gmail, read-only),
  2. upsert raw metadata + body,
  3. compute + store the embedding (pgvector),
  4. run the four stateless processors and persist their outputs + tasks.

Failures on a single email are logged and skipped so one bad email never breaks
the batch.
"""

from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime

from backend.adapters.db.repositories import (
    EmailRepository,
    TaskRepository,
    UserRepository,
)
from backend.adapters.embeddings import EmbeddingClient, get_embedding_client
from backend.adapters.gmail.client import GmailAdapter
from backend.adapters.llm import LLMClient, get_llm_client
from backend.models.rows import StoredEmail, TaskItem
from backend.services import processors

logger = logging.getLogger(__name__)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _parse_due(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


class IngestionService:
    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        embedder: EmbeddingClient | None = None,
        emails: EmailRepository | None = None,
        tasks: TaskRepository | None = None,
        users: UserRepository | None = None,
    ) -> None:
        self._llm = llm or get_llm_client()
        self._embedder = embedder or get_embedding_client()
        self._emails = emails or EmailRepository()
        self._tasks = tasks or TaskRepository()
        self._users = users or UserRepository()

    def ingest_for_user(
        self, user_id: str, gmail: GmailAdapter, limit: int = 10
    ) -> dict[str, int]:
        """Fetch and fully process up to `limit` recent emails. Returns counts.

        Pipeline order: read all -> store raw -> embed ALL in one batched call
        (kept to a single API request to respect provider rate limits) -> triage
        each. Embedding and triage failures are isolated so one bad email or a
        rate-limited embedder never aborts the batch.
        """
        self._users.upsert(user_id)
        summaries = gmail.list_emails(max_results=limit)

        # 1. read + 2. store raw
        details = []
        for summary in summaries:
            try:
                detail = gmail.read_email(summary.id)
                self._emails.upsert_raw(self._to_row(user_id, detail))
                details.append(detail)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to read/store email %s", summary.id)

        # 3. embed ALL in one batched request (graceful if rate-limited)
        self._embed_batch(user_id, details)

        # 4. triage each
        processed = 0
        failed = 0
        for detail in details:
            try:
                self._triage_one(user_id, detail)
                processed += 1
            except Exception:  # noqa: BLE001
                logger.exception("Failed to triage email %s", detail.id)
                failed += 1
        return {"fetched": len(summaries), "processed": processed, "failed": failed}

    @staticmethod
    def _to_row(user_id: str, detail) -> StoredEmail:
        return StoredEmail(
            id=detail.id,
            user_id=user_id,
            thread_id=detail.thread_id,
            sender=detail.sender,
            recipient=detail.to,
            subject=detail.subject,
            snippet=detail.snippet,
            body=detail.body,
            internal_date=_parse_date(detail.date),
            unread=detail.unread,
        )

    def _embed_batch(self, user_id: str, details: list) -> None:
        if not details:
            return
        texts = [f"{d.subject}\n\n{d.body}" for d in details]
        try:
            vectors = self._embedder.embed_batch(texts)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Batch embedding failed (e.g. provider rate limit); continuing "
                "without embeddings for %d emails", len(details)
            )
            return
        for detail, vector in zip(details, vectors):
            try:
                self._emails.set_embedding(user_id, detail.id, vector)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to store embedding for %s", detail.id)

    def _triage_one(self, user_id: str, detail) -> None:
        # stateless triage processors
        kwargs = {"subject": detail.subject, "sender": detail.sender, "body": detail.body}
        classification = processors.classify(self._llm, **kwargs)
        priority = processors.prioritize(self._llm, **kwargs)
        summary = processors.summarize(self._llm, **kwargs)
        extracted = processors.extract_tasks(self._llm, **kwargs)

        self._emails.set_triage(
            user_id,
            detail.id,
            category=classification.category,
            category_confidence=classification.confidence,
            priority=priority.score,
            priority_reason=priority.reason,
            summary_one_line=summary.one_line,
            summary_detailed=summary.detailed,
        )

        # replace tasks for idempotent re-ingestion
        self._tasks.delete_for_email(user_id, detail.id)
        for task in extracted:
            self._tasks.add(
                TaskItem(
                    user_id=user_id,
                    email_id=detail.id,
                    description=task.description,
                    due_date=_parse_due(task.due_date),
                )
            )
