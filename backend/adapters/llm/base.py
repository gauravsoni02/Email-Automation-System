"""The `LLMClient` seam.

This is one of the two interfaces that must survive the whole project (CLAUDE.md
§3). Every model call in the system — stateless processors and LangGraph agents
alike — goes through this interface. Swapping providers touches only the adapter,
never the callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel

Role = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    """A single message in a chat completion request."""

    role: Role
    content: str


class LLMClient(ABC):
    """Provider-agnostic interface for language-model access.

    Concrete adapters (e.g. the Grok client) implement these methods. Callers
    depend only on this abstraction.
    """

    @abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Return a plain-text completion for the given messages."""
        raise NotImplementedError

    @abstractmethod
    def complete_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Return a structured JSON object.

        Used by the stateless triage processors (classify, prioritize,
        summarize, extract) which need reliable structured output.
        """
        raise NotImplementedError
