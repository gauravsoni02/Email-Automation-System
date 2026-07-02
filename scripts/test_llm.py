"""Phase 0 acceptance check: a scripted LLMClient call returns a completion.

Run from the repo root:  python -m scripts.test_llm
Requires LLM_API_KEY (and optionally LLM_MODEL) in your .env.
"""

from __future__ import annotations

import sys

from backend.adapters.llm import ChatMessage, get_llm_client
from backend.config import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.llm_api_key:
        print("LLM_API_KEY is not set. Add it to .env and try again.")
        return 1

    client = get_llm_client()
    messages = [
        ChatMessage(role="system", content="You are a terse assistant."),
        ChatMessage(
            role="user",
            content="Reply with exactly: Aegis Mail AI is online.",
        ),
    ]

    print(f"Calling LLM (model={settings.llm_model})...")
    reply = client.complete(messages, temperature=0.0, max_tokens=32)
    print("LLM replied:")
    print(f"  {reply}")

    # Also exercise the structured-JSON path used by triage processors.
    json_messages = [
        ChatMessage(
            role="user",
            content=(
                'Return a JSON object with keys "service" (string) and "ok" '
                '(boolean) describing that this service is online.'
            ),
        ),
    ]
    payload = client.complete_json(json_messages)
    print("LLM JSON replied:")
    print(f"  {payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
