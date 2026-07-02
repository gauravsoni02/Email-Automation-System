"""Chat assistant route (Phase 6). Checkpointer-backed memory via conversation_id."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.dependencies import current_user_id
from backend.ratelimit import rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    citations: list[dict]


@router.post("", response_model=ChatResponse, dependencies=[Depends(rate_limit("chat", 20, 60))])
def chat(req: ChatRequest, user_id: str = Depends(current_user_id)) -> ChatResponse:
    if not req.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty message.")
    conversation_id = req.conversation_id or uuid.uuid4().hex
    try:
        from backend.agents.chat_agent import ChatAgent
        from backend.agents.checkpointer import get_checkpointer

        agent = ChatAgent(checkpointer=get_checkpointer())
        result = agent.ask(user_id, req.message, conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Chat failed."
        ) from exc
    return ChatResponse(
        answer=result.get("answer", ""),
        conversation_id=conversation_id,
        citations=result.get("context", []),
    )
