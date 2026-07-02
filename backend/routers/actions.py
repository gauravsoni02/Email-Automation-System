"""Action-queue routes — the human-in-the-loop safety gate (Phase 5).

Read pending actions, then **approve** (optionally with edits), or **reject**.
Approval resumes the interrupted LangGraph reply agent, whose executor performs
the real Gmail send — the ONLY path that sends mail, and only on explicit,
authenticated approval. Rejection discards the draft. Nothing sends autonomously.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.adapters.calendar.client import CalendarAdapter
from backend.adapters.db.repositories import ActionQueueRepository
from backend.adapters.gmail.client import GmailAdapter
from backend.dependencies import (
    calendar_adapter_dep,
    current_user_id,
    gmail_adapter_dep,
)
from backend.models.rows import QueuedAction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/actions", tags=["actions"])


class ApproveRequest(BaseModel):
    # optional edits applied to the draft before sending
    subject: str | None = None
    body: str | None = None


@router.get("", response_model=list[QueuedAction])
def list_pending(user_id: str = Depends(current_user_id)) -> list[QueuedAction]:
    return ActionQueueRepository().list_pending(user_id)


@router.get("/{action_id}", response_model=QueuedAction)
def get_action(
    action_id: int, user_id: str = Depends(current_user_id)
) -> QueuedAction:
    action = ActionQueueRepository().get(user_id, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")
    return action


def _load_pending(repo: ActionQueueRepository, user_id: str, action_id: int) -> QueuedAction:
    action = repo.get(user_id, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")
    if action.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Action is '{action.status}', not pending.",
        )
    if not action.graph_thread_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action has no graph checkpoint to resume.",
        )
    return action


@router.post("/{action_id}/approve", response_model=QueuedAction)
def approve(
    action_id: int,
    edits: ApproveRequest | None = None,
    user_id: str = Depends(current_user_id),
    gmail: GmailAdapter = Depends(gmail_adapter_dep),
    calendar: CalendarAdapter = Depends(calendar_adapter_dep),
) -> QueuedAction:
    """Approve (optionally with edits) and execute the action by resuming the graph."""
    repo = ActionQueueRepository()
    action = _load_pending(repo, user_id, action_id)

    # apply human edits to the payload BEFORE the executor reads it
    if edits and (edits.subject is not None or edits.body is not None):
        payload = dict(action.payload)
        if edits.subject is not None:
            payload["subject"] = edits.subject
        if edits.body is not None:
            payload["body"] = edits.body
        repo.update_payload(user_id, action_id, payload)

    # Atomically claim the action so two concurrent approvals can't both send.
    if not repo.claim_pending(user_id, action_id, "approved"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action is no longer pending (already handled).",
        )

    from backend.agents.checkpointer import get_checkpointer
    from backend.agents.reply_agent import ReplyAgent

    agent = ReplyAgent(gmail=gmail, calendar=calendar, checkpointer=get_checkpointer())
    try:
        agent.resume(action.graph_thread_id, approved=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Approval/send failed for action %s", action_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send the approved action.",
        ) from exc

    updated = repo.get(user_id, action_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")
    return updated


@router.post("/{action_id}/reject", response_model=QueuedAction)
def reject(
    action_id: int,
    user_id: str = Depends(current_user_id),
) -> QueuedAction:
    """Reject and discard the draft by resuming the graph down the discard path."""
    repo = ActionQueueRepository()
    action = _load_pending(repo, user_id, action_id)

    if not repo.claim_pending(user_id, action_id, "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action is no longer pending (already handled).",
        )

    from backend.agents.checkpointer import get_checkpointer
    from backend.agents.reply_agent import ReplyAgent

    agent = ReplyAgent(checkpointer=get_checkpointer())
    try:
        agent.resume(action.graph_thread_id, approved=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Reject failed for action %s", action_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to reject the action."
        ) from exc

    updated = repo.get(user_id, action_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")
    return updated
