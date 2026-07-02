"""Follow-up nudges (Phase 7).

Finds important emails that appear to have gone unanswered for N days and, for
each, runs the reply agent with a follow-up instruction. The agent produces a
**pending** action (with a graph checkpoint), so the follow-up is reviewed and
approved through the exact same human-in-the-loop gate as any other send. Nothing
is auto-sent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.adapters.db.repositories import (
    ActionQueueRepository,
    EmailRepository,
)
from backend.agents.reply_agent import ReplyAgent

logger = logging.getLogger(__name__)

_FOLLOWUP_INSTRUCTION = (
    "This email has not been replied to. Write a brief, polite follow-up nudge "
    "checking in. Keep it short."
)


class FollowUpService:
    def __init__(self, checkpointer=None) -> None:
        self._checkpointer = checkpointer

    def scan_and_draft(
        self, user_id: str, *, days: int = 3, min_priority: int = 50, now: datetime | None = None
    ) -> dict[str, int]:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        emails = EmailRepository().list_for_user(user_id, limit=100)
        actions = ActionQueueRepository()
        # Skip emails that already have ANY action (pending, executed, or
        # rejected) so a follow-up isn't re-drafted every scan. NOTE: this is a
        # heuristic for "unanswered" — a fuller version would inspect the Gmail
        # thread for a reply from the user.
        existing = actions.related_email_ids(user_id)

        candidates = [
            e
            for e in emails
            if (e.priority or 0) >= min_priority
            and e.internal_date is not None
            and e.internal_date < cutoff
            and e.id not in existing
        ]
        drafted = 0
        for e in candidates:
            try:
                agent = ReplyAgent(checkpointer=self._checkpointer, now=now)
                agent.run(user_id, e.id, _FOLLOWUP_INSTRUCTION)
                drafted += 1
            except Exception:  # noqa: BLE001
                logger.exception("Follow-up draft failed for email %s", e.id)
        return {"candidates": len(candidates), "drafted": drafted}
