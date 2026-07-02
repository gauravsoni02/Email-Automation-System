"""Ingestion + triaged-data routes (Phase 2).

POST /ingest kicks the pipeline off as a background task. The read routes expose
the triaged results so acceptance can be verified (and the Phase 3 UI can render
them). All access is scoped to the authenticated user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from backend.adapters.db.repositories import EmailRepository, TaskRepository
from backend.adapters.gmail.client import GmailAdapter
from backend.dependencies import current_user_id, gmail_adapter_dep
from backend.models.rows import StoredEmail, TaskItem
from backend.ratelimit import rate_limit
from backend.services.ingestion import IngestionService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ingest"])


def _run_ingestion(user_id: str, gmail: GmailAdapter, limit: int) -> None:
    try:
        result = IngestionService().ingest_for_user(user_id, gmail, limit=limit)
        logger.info("Ingestion for %s complete: %s", user_id, result)
    except Exception:  # noqa: BLE001
        logger.exception("Ingestion for %s failed", user_id)


@router.post("/ingest", dependencies=[Depends(rate_limit("ingest", 6, 60))])
def ingest(
    background: BackgroundTasks,
    limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Depends(current_user_id),
    gmail: GmailAdapter = Depends(gmail_adapter_dep),
) -> dict[str, str]:
    """Start ingesting the user's recent emails in the background."""
    background.add_task(_run_ingestion, user_id, gmail, limit)
    return {"status": "started", "limit": str(limit)}


@router.post("/ingest/sync", dependencies=[Depends(rate_limit("ingest_sync", 6, 60))])
def ingest_sync(
    limit: int = Query(default=5, ge=1, le=20),
    user_id: str = Depends(current_user_id),
    gmail: GmailAdapter = Depends(gmail_adapter_dep),
) -> dict[str, int]:
    """Synchronous ingestion (blocks until done) — handy for verifying acceptance."""
    return IngestionService().ingest_for_user(user_id, gmail, limit=limit)


@router.get("/triaged", response_model=list[StoredEmail])
def list_triaged(
    limit: int = Query(default=20, ge=1, le=100),
    by_priority: bool = Query(default=True),
    user_id: str = Depends(current_user_id),
) -> list[StoredEmail]:
    return EmailRepository().list_for_user(
        user_id, limit=limit, order_by_priority=by_priority
    )


@router.get("/tasks", response_model=list[TaskItem])
def list_tasks(
    user_id: str = Depends(current_user_id),
) -> list[TaskItem]:
    return TaskRepository().list_for_user(user_id)
