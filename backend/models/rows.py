"""Domain row models for persisted state (pydantic mirrors of DB rows)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class StoredEmail(BaseModel):
    id: str
    user_id: str
    thread_id: str | None = None
    sender: str | None = None
    recipient: str | None = None
    subject: str | None = None
    snippet: str | None = None
    body: str | None = None
    internal_date: datetime | None = None
    unread: bool = False

    category: str | None = None
    category_confidence: float | None = None
    priority: int | None = None
    priority_reason: str | None = None
    summary_one_line: str | None = None
    summary_detailed: str | None = None

    created_at: datetime | None = None
    processed_at: datetime | None = None


class TaskItem(BaseModel):
    id: int | None = None
    user_id: str
    email_id: str | None = None
    description: str
    due_date: date | None = None
    status: str = "open"
    created_at: datetime | None = None


class QueuedAction(BaseModel):
    """A row in the action_queue — the safety gate's unit of work."""

    id: int | None = None
    user_id: str
    action_type: str
    status: str = "pending"
    payload: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None
    related_email_id: str | None = None
    graph_thread_id: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
