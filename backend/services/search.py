"""The `SearchService` seam + its Postgres hybrid implementation.

Callers (the search route, and the chat agent in Phase 6) depend only on
`SearchService.search(user_id, query, filters)`. They never touch pgvector or
tsvector directly.

The hybrid implementation composes, in ONE SQL query:
  - semantic similarity (pgvector cosine over the query embedding),
  - keyword rank (Postgres full-text `tsvector` / `plainto_tsquery`),
  - structured metadata filters (category / unread / sender),
all scoped to the authenticated user. Scores are a weighted blend of the two
signals. If the query can't be embedded, it degrades to keyword-only.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SearchFilters(BaseModel):
    """Structured metadata filters applied alongside the text query."""

    category: str | None = None
    unread_only: bool = False
    sender: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    # blend weights for semantic vs keyword signals
    semantic_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    """One hit returned by a search (enriched for UI rendering)."""

    email_id: str
    score: float
    subject: str | None = None
    sender: str | None = None
    snippet: str | None = None
    category: str | None = None
    priority: int | None = None
    summary_one_line: str | None = None
    date: str | None = None


class SearchService(ABC):
    """Provider-agnostic search interface (semantic + keyword + filters)."""

    @abstractmethod
    def search(
        self, user_id: str, query: str, filters: SearchFilters | None = None
    ) -> list[SearchResult]:
        raise NotImplementedError


class StubSearchService(SearchService):
    """Used only when no database is configured."""

    def search(
        self, user_id: str, query: str, filters: SearchFilters | None = None
    ) -> list[SearchResult]:
        raise NotImplementedError(
            "SearchService requires DATABASE_URL (hybrid pgvector + tsvector)."
        )


class PostgresHybridSearchService(SearchService):
    def __init__(self, embedder=None) -> None:
        # lazy imports so this module has no hard DB dependency when unused
        from backend.adapters.embeddings import get_embedding_client

        self._embedder = embedder or get_embedding_client()

    # q.ts uses OR semantics (any term may match) so natural-language questions
    # retrieve broadly; the weighted score then ranks. NULL when the query is all
    # stopwords — handled by COALESCE + the qvec branch.
    _SQL = """
        WITH q AS (
            SELECT to_tsquery(
                'english',
                NULLIF(regexp_replace(
                    plainto_tsquery('english', %(query)s)::text, ' & ', ' | ', 'g'
                ), '')
            ) AS ts
        )
        SELECT
            e.id, e.subject, e.sender, e.snippet, e.category, e.priority,
            e.summary_one_line, e.internal_date,
            CASE WHEN e.embedding IS NOT NULL AND %(qvec)s::vector IS NOT NULL
                 THEN 1 - (e.embedding <=> %(qvec)s::vector) ELSE 0 END AS sem_score,
            COALESCE(ts_rank(e.tsv, q.ts), 0) AS kw_score
        FROM emails e, q
        WHERE e.user_id = %(user_id)s
          AND (%(category)s::text IS NULL OR e.category = %(category)s::text)
          AND (%(unread_only)s = false OR e.unread = true)
          AND (%(sender)s::text IS NULL OR e.sender ILIKE %(sender_like)s::text)
          AND (
                (q.ts IS NOT NULL AND e.tsv @@ q.ts)
                OR (%(qvec)s::vector IS NOT NULL AND e.embedding IS NOT NULL)
              )
        ORDER BY
            (CASE WHEN e.embedding IS NOT NULL AND %(qvec)s::vector IS NOT NULL
                  THEN 1 - (e.embedding <=> %(qvec)s::vector) ELSE 0 END) * %(w_sem)s::float8
            + COALESCE(ts_rank(e.tsv, q.ts), 0) * %(w_kw)s::float8 DESC
        LIMIT %(limit)s
    """

    def search(
        self, user_id: str, query: str, filters: SearchFilters | None = None
    ) -> list[SearchResult]:
        from psycopg.rows import dict_row

        from backend.adapters.db.database import get_connection

        filters = filters or SearchFilters()

        qvec = None
        if query.strip():
            try:
                vec = self._embedder.embed(query)
                qvec = "[" + ",".join(str(float(x)) for x in vec) + "]"
            except Exception:  # noqa: BLE001 - degrade to keyword-only
                logger.exception("Query embedding failed; keyword-only search")

        params = {
            "query": query,
            "qvec": qvec,
            "user_id": user_id,
            "category": filters.category,
            "unread_only": filters.unread_only,
            "sender": filters.sender,
            "sender_like": f"%{filters.sender}%" if filters.sender else None,
            "w_sem": filters.semantic_weight,
            "w_kw": filters.keyword_weight,
            "limit": filters.limit,
        }

        with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(self._SQL, params).fetchall()

        results: list[SearchResult] = []
        for r in rows:
            score = float(r["sem_score"]) * filters.semantic_weight + float(
                r["kw_score"]
            ) * filters.keyword_weight
            results.append(
                SearchResult(
                    email_id=r["id"],
                    score=round(score, 4),
                    subject=r["subject"],
                    sender=r["sender"],
                    snippet=r["snippet"],
                    category=r["category"],
                    priority=r["priority"],
                    summary_one_line=r["summary_one_line"],
                    date=r["internal_date"].isoformat() if r["internal_date"] else None,
                )
            )
        return results


def get_search_service() -> SearchService:
    """Factory: hybrid Postgres search when a DB is configured, else the stub."""
    from backend.config import get_settings

    if get_settings().database_url:
        return PostgresHybridSearchService()
    return StubSearchService()
