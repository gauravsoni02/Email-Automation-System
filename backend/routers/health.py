"""Health/readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.config import get_settings

router = APIRouter(tags=["health"])


def _active_model() -> str:
    from backend.runtime import get_active_model

    return get_active_model()


@router.get("/health")
def health() -> dict[str, object]:
    """Liveness probe: confirms the app is up and reports config presence.

    Does NOT make external calls (no LLM/DB round-trip) — it only reports
    whether the relevant config is present, so it stays fast and dependency-free.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "config": {
            "llm_configured": bool(settings.llm_api_key),
            "llm_model": _active_model(),
            "llm_base_url": settings.llm_base_url,
            "database_configured": bool(settings.database_url),
            "google_oauth_configured": bool(
                settings.google_client_id and settings.google_client_secret
            ),
        },
    }
