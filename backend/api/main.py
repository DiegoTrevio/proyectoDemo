"""AgentOS — FastAPI application entry point."""

import logging
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import agents, billing, memory, stream, tasks
from api.websocket import router as ws_router
from config.langfuse_client import init_langfuse
from config.settings import settings
from db.database import engine
from db.models import Base

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

    yield

    # --- Shutdown ---
    await engine.dispose()


app = FastAPI(
    title="AgentOS",
    description="Autonomous AI Agent Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── CORS ──────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request-ID middleware ─────────────────────────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    logger.info("request_id=%s method=%s path=%s", request_id, request.method, request.url.path)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ─── Error handler ────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": str(exc)},
    )


# ─── Routers ──────────────────────────────────────────────────────────────
app.include_router(tasks.router)
app.include_router(stream.router)
app.include_router(agents.router)
app.include_router(billing.router)
app.include_router(memory.router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
