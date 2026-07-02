"""LLM adapter package.

All model access goes through the `LLMClient` interface. Import the interface
and the factory from here; do not import a concrete provider client directly.
"""

from backend.adapters.llm.base import ChatMessage, LLMClient
from backend.adapters.llm.factory import get_llm_client

__all__ = ["ChatMessage", "LLMClient", "get_llm_client"]
