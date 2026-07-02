"""FastAPI application entry point for Aegis Mail AI.

Owns auth, orchestration, service routes, and (from Phase 5) the approval
endpoints. Run with:  uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import get_settings
from backend.routers import (
    actions,
    agent,
    auth,
    chat,
    digest,
    emails,
    events,
    health,
    ingest,
    models,
    search,
)
from backend.scheduler.jobs import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 7: start the daily follow-up + digest scheduler (if enabled).
    start_scheduler()
    yield
    shutdown_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Personal inbox + calendar assistant with a human-in-the-loop safety gate.",
        lifespan=lifespan,
    )
    for module in (
        health, auth, emails, events, ingest, search, agent, actions, chat,
        digest, models,
    ):
        app.include_router(module.router)
    return app


app = create_app()
