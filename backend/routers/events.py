"""Read-only calendar routes (Phase 1). Scoped to the authenticated user.
No event-create endpoint exists yet (that is gated behind Phase 5).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.adapters.calendar.client import CalendarAdapter, CalendarError
from backend.dependencies import calendar_adapter_dep
from backend.models.schemas import CalendarEvent, FreeBusySlot

router = APIRouter(prefix="/events", tags=["events"])


def _today_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


@router.get("/today", response_model=list[CalendarEvent])
def todays_events(
    calendar: CalendarAdapter = Depends(calendar_adapter_dep),
) -> list[CalendarEvent]:
    start, end = _today_bounds()
    try:
        return calendar.list_events(start, end)
    except CalendarError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/free-busy", response_model=list[FreeBusySlot])
def free_busy(
    days_ahead: int = Query(default=1, ge=1, le=14),
    calendar: CalendarAdapter = Depends(calendar_adapter_dep),
) -> list[FreeBusySlot]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days_ahead)
    try:
        return calendar.get_free_busy(start, end)
    except CalendarError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
