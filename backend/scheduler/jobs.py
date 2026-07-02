"""Scheduled jobs (Phase 7) — a simple APScheduler background scheduler.

No Redis/Temporal/BullMQ (see CLAUDE.md guardrails). Runs a daily follow-up scan
for every user (drafts pending nudges — never auto-sends). The digest is assembled
on demand via GET /digest; a daily digest job logs a summary per user.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from backend.config import get_settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_followup_all_users() -> None:
    from backend.adapters.db.repositories import UserRepository
    from backend.agents.checkpointer import get_checkpointer
    from backend.services.followup import FollowUpService

    try:
        service = FollowUpService(checkpointer=get_checkpointer())
        for user_id in UserRepository().list_ids():
            result = service.scan_and_draft(user_id)
            logger.info("Follow-up scan for %s: %s", user_id, result)
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled follow-up scan failed")


def _run_digest_all_users() -> None:
    from backend.adapters.db.repositories import UserRepository
    from backend.services.digest import DigestService

    try:
        service = DigestService()
        for user_id in UserRepository().list_ids():
            digest = service.build(user_id)  # no calendar in the background job
            logger.info(
                "Digest for %s: %d priorities, %d pending, %d tasks",
                user_id,
                len(digest["top_priorities"]),
                len(digest["pending_replies"]),
                len(digest["tasks_due"]),
            )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled digest failed")


def start_scheduler() -> None:
    """Start the background scheduler once, if enabled and a DB is configured."""
    global _scheduler
    settings = get_settings()
    if not settings.enable_scheduler or not settings.database_url:
        logger.info("Scheduler disabled or no DATABASE_URL; not starting.")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_followup_all_users, "interval", hours=24, id="followup", replace_existing=True
    )
    _scheduler.add_job(
        _run_digest_all_users, "interval", hours=24, id="digest", replace_existing=True
    )
    _scheduler.start()
    logger.info("Scheduler started (follow-up + digest, every 24h).")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
