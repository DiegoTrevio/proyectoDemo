"""Task worker — persistent job queue for agent orchestration.

Replaces the fire-and-forget asyncio.create_task() pattern with arq,
a Redis-based async job queue. Tasks survive server restarts and
are retried on failure.

Run with: arq workers.task_worker.WorkerSettings
"""

import logging
from datetime import datetime, timezone

from arq.connections import RedisSettings

from config.settings import settings

logger = logging.getLogger("agentos.worker")


async def execute_task(ctx: dict, task_id: str, goal: str, config: dict | None) -> str:
    """Execute a task via the orchestrator. Called by arq worker.

    This is the persistent equivalent of the old _run_orchestrator() function.
    If it fails, arq will retry up to max_tries times.
    """
    from agents.orchestrator import run_task
    from db.database import async_session
    from db.models import Task

    logger.info("Worker picked up task=%s goal=%s", task_id, goal[:80])

    # Update status to running
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task:
            logger.error("Task %s not found in DB — skipping", task_id)
            return "not_found"
        if task.status == "cancelled":
            logger.info("Task %s was cancelled — skipping", task_id)
            return "cancelled"
        task.status = "running"
        task.updated_at = datetime.now(timezone.utc)
        await db.commit()

    try:
        final_output = await run_task(task_id, goal, config)
        status = "completed"
        result = {"output": final_output}
    except Exception as e:
        logger.exception("Orchestrator failed for task %s", task_id)
        status = "failed"
        result = {"error": str(e)}

    # Persist final state
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if task:
            task.status = status
            task.result = result
            task.updated_at = datetime.now(timezone.utc)
            await db.commit()

    logger.info("Task %s finished with status=%s", task_id, status)
    return status


async def startup(ctx: dict) -> None:
    """Called when the worker starts. Initialize shared resources."""
    logger.info("Task worker starting")


async def shutdown(ctx: dict) -> None:
    """Called when the worker shuts down. Clean up resources."""
    logger.info("Task worker shutting down")


def _parse_redis_settings() -> RedisSettings:
    """Parse Redis URL from settings into arq RedisSettings."""
    url = settings.redis_url
    # redis://host:port or redis://host:port/db
    if url.startswith("redis://"):
        url = url[len("redis://"):]
    host_port = url.split("/")[0]
    db = int(url.split("/")[1]) if "/" in url else 0
    host = host_port.split(":")[0] if ":" in host_port else host_port
    port = int(host_port.split(":")[1]) if ":" in host_port else 6379
    return RedisSettings(host=host, port=port, database=db)


class WorkerSettings:
    """arq worker configuration."""
    functions = [execute_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _parse_redis_settings()
    max_jobs = 10
    job_timeout = 600        # 10 minutes max per task
    max_tries = 3            # Retry failed tasks up to 3 times
    retry_defer = 10         # Wait 10 seconds before retry
    health_check_interval = 30
    queue_name = "agentos:tasks"
