"""Digest + follow-up routes (Phase 7)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from backend.adapters.calendar.client import CalendarAdapter
from backend.dependencies import calendar_adapter_dep, current_user_id
from backend.ratelimit import rate_limit
from backend.services.digest import DigestService
from backend.services.followup import FollowUpService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["digest"])


@router.get("/digest")
def get_digest(
    user_id: str = Depends(current_user_id),
    calendar: CalendarAdapter = Depends(calendar_adapter_dep),
) -> dict:
    return DigestService().build(user_id, calendar=calendar)


@router.post("/followup/scan", dependencies=[Depends(rate_limit("followup", 5, 60))])
def followup_scan(
    days: int = Query(default=3, ge=0, le=60),
    min_priority: int = Query(default=50, ge=0, le=100),
    user_id: str = Depends(current_user_id),
) -> dict:
    from backend.agents.checkpointer import get_checkpointer

    return FollowUpService(checkpointer=get_checkpointer()).scan_and_draft(
        user_id, days=days, min_priority=min_priority
    )
