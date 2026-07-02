"""Reply/scheduling agent route (Phase 4).

POST /agent/reply runs the LangGraph reply agent for one email and returns the
PENDING action it created. No email is sent — the draft lands in action_queue for
human approval (Phase 5).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.adapters.calendar.client import CalendarAdapter
from backend.agents.reply_agent import ReplyAgent
from backend.dependencies import calendar_adapter_dep, current_user_id
from backend.models.rows import QueuedAction
from backend.ratelimit import rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


class ReplyRequest(BaseModel):
    email_id: str
    instruction: str | None = None


@router.post(
    "/reply",
    response_model=QueuedAction,
    dependencies=[Depends(rate_limit("agent_reply", 15, 60))],
)
def draft_reply(
    req: ReplyRequest,
    user_id: str = Depends(current_user_id),
    calendar: CalendarAdapter = Depends(calendar_adapter_dep),
) -> QueuedAction:
    """Run the reply agent; returns the pending draft action (never sends)."""
    try:
        from backend.agents.checkpointer import get_checkpointer

        agent = ReplyAgent(calendar=calendar, checkpointer=get_checkpointer())
        result = agent.run(user_id, req.email_id, req.instruction)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Reply agent failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Reply agent failed."
        ) from exc

    action_id = result.get("action_id")
    if action_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent did not produce a pending action.",
        )
    from backend.adapters.db.repositories import ActionQueueRepository

    action = ActionQueueRepository().get(user_id, action_id)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pending action not found after creation.",
        )
    return action
