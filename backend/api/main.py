"""AgentOS — FastAPI application entry point."""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.middleware.rate_limiter import RateLimitMiddleware
from api.routes import agents, api_keys, billing, dashboard, ingest, memory, project, skills, stream, tasks
from integrations.openclaw_bridge import create_openclaw_router
from api.websocket import router as ws_router
from config.langfuse_client import init_langfuse
from config.logging_config import setup_logging
from config.settings import settings
from db.database import engine
from db.models import Base

setup_logging()
logger = logging.getLogger("agentos")


def _validate_environment() -> list[str]:
    """Validate required environment variables at startup. Returns list of warnings."""
    warnings = []

    # Critical: database must be configured
    if "localhost" in settings.database_url or "postgres:5432" in settings.database_url:
        if os.environ.get("TESTING") != "1":
            warnings.append("DATABASE_URL uses default/docker host — ensure this is correct for your environment")

    # Security: API key salt should be set explicitly for persistence
    if not os.environ.get("API_KEY_SALT"):
        warnings.append("API_KEY_SALT not set — using random value (API keys will NOT survive restarts!)")

    # Security: CORS origins should be explicit in production
    if "localhost" in settings.cors_origins:
        warnings.append("CORS_ORIGINS contains localhost — update for production domains")

    return warnings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle: connect to Redis, PostgreSQL, Langfuse."""
    # --- Startup ---
    # Environment validation
    env_warnings = _validate_environment()
    for warning in env_warnings:
        logger.warning("ENV: %s", warning)

    # PostgreSQL: create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL connected — tables ensured")

    # Redis: verify connectivity
    try:
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=5)
        await r.ping()
        await r.close()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis not available: %s — rate limiting and streaming will be degraded", e)

    # Langfuse
    lf = init_langfuse()
    if lf:
        logger.info("Langfuse initialized")
    else:
        logger.warning("Langfuse keys not configured — tracing disabled")

    # DeerFlow 2.0: check connectivity (non-blocking, service may start later)
    if settings.deerflow_enabled:
        try:
            from tools.deerflow_client import get_deerflow_client
            client = get_deerflow_client()
            if await client.health_check():
                logger.info("DeerFlow 2.0 connected (gateway + langgraph)")
            else:
                logger.warning("DeerFlow 2.0 not yet available — will retry on first use")
        except Exception as e:
            logger.warning("DeerFlow 2.0 check failed: %s — will retry on first use", e)

    # arq: create connection pool for task enqueueing
    try:
        from arq import create_pool
        from workers.task_worker import WorkerSettings
        app.state.arq_pool = await create_pool(WorkerSettings.redis_settings)
        logger.info("arq pool connected (queue: %s)", WorkerSettings.queue_name)
    except Exception as e:
        app.state.arq_pool = None
        logger.warning("arq pool not available: %s — tasks will run inline (dev mode)", e)

    # Recovery: re-enqueue tasks that were stuck as "running" (server crash recovery)
    try:
        from sqlalchemy import select as sa_select
        from db.models import Task
        async with engine.begin() as conn:
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(engine) as db:
                result = await db.execute(
                    sa_select(Task).where(Task.status == "running")
                )
                stuck_tasks = result.scalars().all()
                if stuck_tasks:
                    logger.warning("Found %d stuck tasks from previous crash — re-enqueueing", len(stuck_tasks))
                    for task in stuck_tasks:
                        task.status = "queued"
                        task.updated_at = datetime.now(timezone.utc)
                        if app.state.arq_pool:
                            await app.state.arq_pool.enqueue_job(
                                "execute_task", task.id, task.goal, task.config,
                                _queue_name="agentos:tasks",
                            )
                    await db.commit()
                    logger.info("Re-enqueued %d stuck tasks", len(stuck_tasks))
    except Exception as e:
        logger.warning("Task recovery check failed: %s", e)

    logger.info("AgentOS v0.1.0 started (%d env warnings)", len(env_warnings))

    yield

    # --- Shutdown ---
    if getattr(app, "state", None) and getattr(app.state, "arq_pool", None):
        await app.state.arq_pool.close()
    await engine.dispose()
    logger.info("AgentOS shutdown complete")


app = FastAPI(
    title="AgentOS",
    description="Autonomous AI Agent Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── Rate Limiting ────────────────────────────────────────────────────────
app.add_middleware(RateLimitMiddleware)

# ─── Billing Enforcement ─────────────────────────────────────────────────
from integrations.billing_middleware import BillingMiddleware  # noqa: E402
app.add_middleware(BillingMiddleware)

# ─── CORS ──────────────────────────────────────────────────────────────────
_cors_origins = [
    o.strip()
    for o in settings.cors_origins.split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


# ─── Security + Request-ID middleware ──────────────────────────────────────
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    logger.info("request_id=%s method=%s path=%s", request_id, request.method, request.url.path)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ─── Error handler ────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "An unexpected error occurred."},
    )


# ─── Routers ──────────────────────────────────────────────────────────────
app.include_router(tasks.router)
app.include_router(stream.router)
app.include_router(agents.router)
app.include_router(billing.router)
app.include_router(memory.router)
app.include_router(ws_router)
app.include_router(ingest.router)
app.include_router(dashboard.router)
app.include_router(api_keys.router)
app.include_router(project.router)
app.include_router(skills.router)
app.include_router(create_openclaw_router())


@app.get("/health")
async def health():
    return {"status": "ok"}
