"""Output models for the stateless triage processors."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Classification(BaseModel):
    category: str
    confidence: float = Field(ge=0.0, le=1.0)


class Priority(BaseModel):
    score: int = Field(ge=0, le=100)
    reason: str


class Summary(BaseModel):
    one_line: str
    detailed: str
    action_items: list[str] = Field(default_factory=list)


class ExtractedTask(BaseModel):
    description: str
    due_date: str | None = None  # ISO date string if the email implies one


# Allowed categories for classification (kept small and stable).
CATEGORIES = [
    "urgent",
    "finance",
    "meeting",
    "personal",
    "work",
    "newsletter",
    "promotion",
    "notification",
    "spam",
    "other",
]
