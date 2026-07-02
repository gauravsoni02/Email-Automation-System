"""The `EmbeddingClient` seam — provider-agnostic text embeddings."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingClient(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension produced by this client (must match the DB schema)."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single text."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in one call (batched for efficiency)."""
