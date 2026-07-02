"""Pydantic schemas used at API boundaries (Phase 1: email + calendar reads).

These are transport/DTO models. ORM models for persisted state arrive in Phase 2.
"""

from __future__ import annotations

from pydantic import BaseModel


class EmailSummary(BaseModel):
    """Lightweight metadata for an inbox listing."""

    id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    date: str
    unread: bool


class EmailDetail(EmailSummary):
    """A single email with its extracted plain-text body."""

    to: str
    body: str


class CalendarEvent(BaseModel):
    """A calendar event in a listing."""

    id: str
    summary: str
    start: str | None
    end: str | None
    location: str | None = None
    attendees: list[str] = []


class FreeBusySlot(BaseModel):
    """A busy interval from the free/busy query."""

    start: str
    end: str


class LoginStartResponse(BaseModel):
    authorization_url: str


class WhoAmIResponse(BaseModel):
    user_id: str
