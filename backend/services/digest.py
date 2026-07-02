"""Daily digest assembly (Phase 7).

Composes the morning digest from existing state: top priorities, pending replies
awaiting approval, tasks due, and (if calendar creds are available) upcoming
meetings. Pure read-only composition over repositories + the calendar adapter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.adapters.calendar.client import CalendarAdapter, CalendarError
from backend.adapters.db.repositories import (
    ActionQueueRepository,
    EmailRepository,
    TaskRepository,
)

logger = logging.getLogger(__name__)


class DigestService:
    def build(self, user_id: str, calendar: CalendarAdapter | None = None) -> dict:
        emails = EmailRepository().list_for_user(
            user_id, limit=50, order_by_priority=True
        )
        top = [
            {
                "id": e.id,
                "subject": e.subject,
                "sender": e.sender,
                "priority": e.priority,
                "summary": e.summary_one_line,
            }
            for e in emails
            if (e.priority or 0) > 0
        ][:5]

        pending = [
            {
                "id": a.id,
                "type": a.action_type,
                "to": a.payload.get("to"),
                "subject": a.payload.get("subject"),
            }
            for a in ActionQueueRepository().list_pending(user_id)
        ]

        tasks = [
            {"description": t.description, "due_date": str(t.due_date) if t.due_date else None}
            for t in TaskRepository().list_for_user(user_id)
        ]

        meetings: list[dict] = []
        if calendar is not None:
            try:
                start = datetime.now(timezone.utc)
                end = start + timedelta(days=1)
                meetings = [
                    {"summary": ev.summary, "start": ev.start, "end": ev.end}
                    for ev in calendar.list_events(start, end)
                ]
            except CalendarError:
                logger.exception("digest calendar lookup failed")

        return {
            "top_priorities": top,
            "pending_replies": pending,
            "upcoming_meetings": meetings,
            "tasks_due": tasks,
        }
