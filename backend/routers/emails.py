"""Read-only email routes (Phase 1). All access is scoped to the authenticated
user via `gmail_adapter_dep`. No mutation endpoints exist yet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.adapters.gmail.client import GmailAdapter, GmailError
from backend.dependencies import gmail_adapter_dep
from backend.models.schemas import EmailDetail, EmailSummary

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=list[EmailSummary])
def list_emails(
    limit: int = Query(default=10, ge=1, le=50),
    gmail: GmailAdapter = Depends(gmail_adapter_dep),
) -> list[EmailSummary]:
    try:
        return gmail.list_emails(max_results=limit)
    except GmailError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/{message_id}", response_model=EmailDetail)
def read_email(
    message_id: str,
    gmail: GmailAdapter = Depends(gmail_adapter_dep),
) -> EmailDetail:
    try:
        return gmail.read_email(message_id)
    except GmailError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
