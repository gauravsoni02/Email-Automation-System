"""Central configuration for Aegis Mail AI.

Everything sensitive or environment-specific is loaded from the environment
(via a local `.env` in development). Per CLAUDE.md, the Grok model name lives
here and is never hardcoded elsewhere in the codebase.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Aegis Mail AI"
    environment: str = Field(default="development")
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)

    # --- Database (hosted Postgres + pgvector, e.g. Neon/Supabase) ---
    # Not required to boot in Phase 0; wired up for real in Phase 2 (ingestion).
    database_url: str | None = Field(default=None)

    # --- LLM (OpenAI-compatible provider; default GroqCloud). ---
    # The provider is entirely config-driven. This works with any OpenAI-compatible
    # endpoint (Groq, xAI/Grok, OpenAI, ...); swapping providers is an env change,
    # never a code change, thanks to the LLMClient seam.
    llm_api_key: str | None = Field(default=None)
    llm_model: str = Field(default="llama-3.3-70b-versatile")
    llm_base_url: str = Field(default="https://api.groq.com/openai/v1")
    llm_timeout_seconds: float = Field(default=30.0)
    llm_max_retries: int = Field(default=2)
    # Models the UI can switch between at runtime (same provider/base URL).
    llm_available_models: str = Field(
        default="llama-3.3-70b-versatile,llama-3.1-8b-instant"
    )

    # --- Embeddings (behind the EmbeddingClient seam). Groq has no embeddings
    #     API, so this defaults to Google Gemini's OpenAI-compatible endpoint
    #     (free tier). EMBEDDING_DIM must match vector(...) in schema.sql. ---
    embedding_api_key: str | None = Field(default=None)
    embedding_model: str = Field(default="gemini-embedding-001")
    embedding_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    embedding_dim: int = Field(default=768)

    # --- Google OAuth (used from Phase 1 onward) ---
    google_client_id: str | None = Field(default=None)
    google_client_secret: str | None = Field(default=None)
    google_redirect_uri: str = Field(default="http://localhost:8000/auth/callback")
    # Minimal scopes: read-only mail/calendar + compose/modify for gated sends.
    google_scopes: str = Field(
        default=(
            "https://www.googleapis.com/auth/gmail.readonly "
            "https://www.googleapis.com/auth/gmail.compose "
            "https://www.googleapis.com/auth/calendar.readonly "
            "https://www.googleapis.com/auth/calendar.events"
        )
    )

    # --- Secrets ---
    # Fernet key used to encrypt OAuth tokens at rest (Phase 1).
    token_encryption_key: str | None = Field(default=None)

    # --- Token storage (Phase 1 interim: encrypted file; Postgres in Phase 2) ---
    token_store_path: str = Field(default=".aegis_tokens.json")
    # Signed/encrypted session cookie name for the logged-in user.
    session_cookie_name: str = Field(default="aegis_session")
    # Max session lifetime (seconds). Session tokens expire after this. 7 days.
    session_ttl_seconds: int = Field(default=60 * 60 * 24 * 7)

    # --- Frontend (Streamlit). After OAuth the callback hands the session token
    #     back to the Streamlit app so its server-side requests are authenticated. ---
    frontend_url: str = Field(default="http://localhost:8501")

    # --- Scheduler (Phase 7). Daily follow-up scan + digest. ---
    enable_scheduler: bool = Field(default=False)

    @property
    def google_scopes_list(self) -> list[str]:
        return [s for s in self.google_scopes.split() if s]

    @property
    def llm_available_models_list(self) -> list[str]:
        return [m.strip() for m in self.llm_available_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Import this everywhere config is needed."""
    return Settings()
