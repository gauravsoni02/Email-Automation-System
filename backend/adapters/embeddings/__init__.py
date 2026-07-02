"""Embedding adapter package.

All embedding generation goes through the `EmbeddingClient` interface, mirroring
the `LLMClient` seam. xAI (Grok) has no embeddings endpoint, so the concrete
implementation targets an OpenAI-compatible provider selected in config.
"""

from backend.adapters.embeddings.base import EmbeddingClient
from backend.adapters.embeddings.factory import get_embedding_client

__all__ = ["EmbeddingClient", "get_embedding_client"]
