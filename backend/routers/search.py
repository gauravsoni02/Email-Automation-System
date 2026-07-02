"""Search route (Phase 3). Delegates to the `SearchService` seam — the router
knows nothing about pgvector/tsvector. Scoped to the authenticated user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.dependencies import current_user_id
from backend.ratelimit import rate_limit
from backend.services.search import SearchFilters, SearchResult, get_search_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "", response_model=list[SearchResult],
    dependencies=[Depends(rate_limit("search", 30, 60))],
)
def search(
    q: str = Query(..., min_length=1, description="Natural-language or keyword query"),
    category: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    sender: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(current_user_id),
) -> list[SearchResult]:
    filters = SearchFilters(
        category=category, unread_only=unread_only, sender=sender, limit=limit
    )
    try:
        return get_search_service().search(user_id, q, filters)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Search failed."
        ) from exc
