"""Runtime-adjustable settings that the UI can change without a restart.

Currently just the active LLM model. Kept deliberately tiny — a process-local
override that falls back to the configured default. (Single-process MVP; a
multi-worker deployment would persist this per-user.)
"""

from __future__ import annotations

from backend.config import get_settings

_active_model: str | None = None


def get_active_model() -> str:
    return _active_model or get_settings().llm_model


def set_active_model(model: str) -> None:
    global _active_model
    _active_model = model


def available_models() -> list[str]:
    settings = get_settings()
    models = list(settings.llm_available_models_list)
    if settings.llm_model not in models:
        models.insert(0, settings.llm_model)
    return models
