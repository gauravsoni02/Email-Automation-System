"""Factory for the active `LLMClient` implementation.

Callers ask for `get_llm_client()` and receive whatever provider config selects.
Today that is always Grok; swapping providers means changing only this function.
"""

from __future__ import annotations

from backend.adapters.llm.base import LLMClient
from backend.adapters.llm.openai_compat import OpenAICompatLLMClient
from backend.config import get_settings

# one client per model, built on demand (so the UI can switch models at runtime)
_clients: dict[str, LLMClient] = {}


def get_llm_client() -> LLMClient:
    from backend.runtime import get_active_model

    model = get_active_model()
    if model not in _clients:
        _clients[model] = OpenAICompatLLMClient(get_settings(), model=model)
    return _clients[model]
