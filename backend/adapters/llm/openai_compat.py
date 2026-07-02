"""OpenAI-compatible implementation of the `LLMClient` interface.

Groq (GroqCloud), xAI (Grok), and OpenAI all speak the same OpenAI wire protocol,
so a single client covers them — the provider is selected purely by config
(api key, base URL, model). Nothing about a specific provider is hardcoded
outside `config.py`.
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from backend.adapters.llm.base import ChatMessage, LLMClient
from backend.config import Settings


class OpenAICompatLLMClient(LLMClient):
    """Talks to any OpenAI-compatible chat-completions endpoint."""

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        if not settings.llm_api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Add your provider key (e.g. a GroqCloud "
                "key from console.groq.com) to your .env (see .env.example)."
            )
        self._model = model or settings.llm_model
        self._client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[m.model_dump() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()

    def complete_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        # OpenAI-compatible JSON mode. Note: Groq (like OpenAI) requires the word
        # "json" to appear in the prompt when using json_object mode — the triage
        # processors' prompts already include it.
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[m.model_dump() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
