"""Lightweight in-memory rate limiting (Phase 8 hardening).

A fixed-window limiter keyed by (route, user). In-memory is sufficient for the
single-process MVP — no Redis (see CLAUDE.md guardrails). Returns HTTP 429 when
a caller exceeds the limit on an expensive/abusable endpoint.
"""

from __future__ import annotations

import threading
import time

from fastapi import Depends, HTTPException, status

from backend.dependencies import current_user_id

# (route, user) -> list[timestamps] within the current window
_hits: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()


def rate_limit(name: str, max_calls: int, window_seconds: int):
    """Return a FastAPI dependency enforcing `max_calls` per `window_seconds`."""

    def _dep(user_id: str = Depends(current_user_id)) -> None:
        key = (name, user_id)
        now = time.time()
        with _lock:  # threadpool-safe: read-modify-write under a lock
            recent = [t for t in _hits.get(key, []) if now - t < window_seconds]
            if len(recent) >= max_calls:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded for {name}. Try again shortly.",
                )
            recent.append(now)
            if recent:
                _hits[key] = recent
            else:
                _hits.pop(key, None)  # evict empty windows

    return _dep
