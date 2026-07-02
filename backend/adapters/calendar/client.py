"""Calendar adapter — READ-ONLY in Phase 1.

Exposes `list_events` and `get_free_busy`. No event-create method here: the gated
create path arrives in Phase 5 and MUST route through the `action_queue`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.models.schemas import CalendarEvent, FreeBusySlot


class CalendarError(RuntimeError):
    """Raised when the Calendar API call fails; carries a safe message."""


def _rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class CalendarAdapter:
    def __init__(self, credentials: Credentials) -> None:
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def list_events(
        self, time_min: datetime, time_max: datetime, calendar_id: str = "primary"
    ) -> list[CalendarEvent]:
        try:
            result = (
                self._service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=_rfc3339(time_min),
                    timeMax=_rfc3339(time_max),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except HttpError as exc:
            raise CalendarError("Failed to list calendar events.") from exc

        events: list[CalendarEvent] = []
        for item in result.get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            events.append(
                CalendarEvent(
                    id=item.get("id", ""),
                    summary=item.get("summary", "(no title)"),
                    start=start.get("dateTime") or start.get("date"),
                    end=end.get("dateTime") or end.get("date"),
                    location=item.get("location"),
                    attendees=[
                        a.get("email", "")
                        for a in item.get("attendees", [])
                        if a.get("email")
                    ],
                )
            )
        return events

    def get_free_busy(
        self, time_min: datetime, time_max: datetime, calendar_id: str = "primary"
    ) -> list[FreeBusySlot]:
        try:
            result = (
                self._service.freebusy()
                .query(
                    body={
                        "timeMin": _rfc3339(time_min),
                        "timeMax": _rfc3339(time_max),
                        "items": [{"id": calendar_id}],
                    }
                )
                .execute()
            )
        except HttpError as exc:
            raise CalendarError("Failed to query free/busy.") from exc

        cal = result.get("calendars", {}).get(calendar_id, {})
        return [
            FreeBusySlot(start=b["start"], end=b["end"]) for b in cal.get("busy", [])
        ]
