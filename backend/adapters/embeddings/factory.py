"""Factory for the active `EmbeddingClient` implementation."""

from __future__ import annotations

from functools import lru_cache

from backend.adapters.embeddings.base import EmbeddingClient
from backend.adapters.embeddings.openai_client import OpenAIEmbeddingClient
from backend.config import get_settings


@lru_cache
def get_embedding_client() -> EmbeddingClient:
    return OpenAIEmbeddingClient(get_settings())
