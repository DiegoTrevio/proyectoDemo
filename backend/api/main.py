"""AgentOS — FastAPI application entry point."""

import logging
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.middleware.rate_limiter import RateLimitMiddleware
from api.routes import agents, api_keys, billing, dashboard, ingest, memory, stream, tasks
from api.websocket import router as ws_router
from config.langfuse_client import init_langfuse
from config.logging_config import setup_logging
from config.settings import settings
from db.database import engine
from db.models import Base

setup_logging()
logger = logging.getLogger("agentos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle: connect to Redis, PostgreSQL, Langfuse."""
    # --- Startup ---
    # PostgreSQL: create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL connected — tables ensured")

    # Redis: verify connectivity
    r = aioredis.from_url(settings.redis_url)
    await r.ping()
    await r.close()
    logger.info("Redis connected")

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

    yield

    # --- Shutdown ---
    await engine.dispose()


app = FastAPI(
    title="AgentOS",
    description="Autonomous AI Agent Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── Rate Limiting ────────────────────────────────────────────────────────
app.add_middleware(RateLimitMiddleware)

# ─── CORS ──────────────────────────────────────────────────────────────────
_cors_origins = [
    o.strip()
    for o in (settings.cors_origins or "http://localhost:3000").split(",")
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


@app.get("/health")
async def health():
    return {"status": "ok"}
