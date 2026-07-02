"""OpenAI-compatible embedding client.

Works with OpenAI or any OpenAI-compatible embeddings endpoint. Model, base URL,
key, and dimension all come from config — nothing is hardcoded outside here.
"""

from __future__ import annotations

from openai import OpenAI

from backend.adapters.embeddings.base import EmbeddingClient
from backend.config import Settings


class OpenAIEmbeddingClient(EmbeddingClient):
    def __init__(self, settings: Settings) -> None:
        if not settings.embedding_api_key:
            raise RuntimeError(
                "EMBEDDING_API_KEY is not set. Add an OpenAI-compatible embeddings "
                "key to your .env (see .env.example)."
            )
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._client = OpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Newlines can degrade some embedding models; normalise lightly.
        cleaned = [t.replace("\n", " ") if t else " " for t in texts]
        # Pass the target dimension explicitly. Gemini's gemini-embedding-001
        # defaults to 3072 (too large for the pgvector index) but honours a
        # reduced `dimensions`; OpenAI's text-embedding-3-* honour it too.
        response = self._client.embeddings.create(
            model=self._model, input=cleaned, dimensions=self._dim
        )
        return [item.embedding for item in response.data]
