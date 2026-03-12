"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from app.config import get_settings
from app.logging_config import setup_logging
from app.routers.chatwoot import router as chatwoot_router
from app.routers.evolution import router as evolution_router
from app.services.chatwoot import ChatwootClient
from app.services.evolution import EvolutionClient
from app.services.pg_listener import run_pg_listener

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage the shared httpx client, ChatwootClient, Redis, and PG listener."""
    settings = get_settings()
    setup_logging(settings.log_level)

    redis_client: Redis | None = None
    pg_listener_task: asyncio.Task[None] | None = None
    if settings.redis_url:
        try:
            redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
            await redis_client.ping()
            # Debug: show Redis URL (password redacted)
            redacted_url = re.sub(r":([^@/:]+)@", ":***@", settings.redis_url)
            logger.info("Redis connected: %s", redacted_url)
        except Exception:
            logger.warning("Redis unavailable — broadcast triggers disabled", exc_info=True)
            redis_client = None

    application.state.redis_client = redis_client

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as http_client:
        chatwoot_client = ChatwootClient(
            base_url=settings.chatwoot_base_url,
            api_token=settings.chatwoot_api_token,
            account_ids=settings.chatwoot_account_ids,
            http_client=http_client,
        )
        await chatwoot_client.build_inbox_map()
        application.state.chatwoot_client = chatwoot_client

        evolution_client: EvolutionClient | None = None
        if settings.evolution_api_url and settings.evolution_api_key:
            evolution_client = EvolutionClient(
                base_url=settings.evolution_api_url,
                api_key=settings.evolution_api_key,
                http_client=http_client,
            )
            logger.info(
                "Evolution API client initialized: %s",
                settings.evolution_api_url,
            )
        else:
            logger.warning(
                "Evolution API not configured — LID resolution disabled",
            )
        application.state.evolution_client = evolution_client

        if settings.chatwoot_database_url and evolution_client:
            pg_listener_task = asyncio.create_task(
                run_pg_listener(
                    settings.chatwoot_database_url,
                    chatwoot_client,
                    evolution_client,
                ),
            )
            logger.info("PG listener started (Layer 2: agent view detection)")
        elif settings.chatwoot_database_url and not evolution_client:
            logger.warning(
                "CHATWOOT_DATABASE_URL set but Evolution API not configured — "
                "PG listener disabled",
            )

        logger.info(
            "Service started — Chatwoot: %s (accounts: %s)",
            settings.chatwoot_base_url,
            settings.chatwoot_account_ids,
        )
        yield

    if pg_listener_task is not None:
        pg_listener_task.cancel()
        try:
            await pg_listener_task
        except asyncio.CancelledError:
            pass

    if redis_client:
        await redis_client.aclose()
    logger.info("Service stopped")


app = FastAPI(
    title="Chatwoot Read Sync",
    description=(
        "Bidirectional read sync between Chatwoot and WhatsApp via Evolution API: "
        "(1) WhatsApp→Chatwoot: marks Chatwoot as read when messages are read on phone; "
        "(2) Chatwoot→WhatsApp: sends read receipts when agents view or reply in Chatwoot."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(evolution_router)
app.include_router(chatwoot_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
