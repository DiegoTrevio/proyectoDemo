"""Redis session layer — ephemeral state for tasks, agents, and SSE subscribers.

Manages short-lived state with 24-hour TTL:
  - Task state: current execution status, step progress
  - Agent state: intermediate results, scratch data
  - SSE subscribers: active event stream connections
  - Session context: user session data across requests
"""

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from config.settings import settings

logger = logging.getLogger("agentos.memory.redis_session")

SESSION_TTL = 86400  # 24 hours


def _get_redis() -> aioredis.Redis:
    """Create a Redis connection."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


# ── Task state ────────────────────────────────────────────────────────────

async def set_task_state(task_id: str, state: dict, ttl: int = SESSION_TTL) -> None:
    """Store task execution state."""
    r = _get_redis()
    try:
        key = f"task:{task_id}:state"
        await r.set(key, json.dumps(state, default=str), ex=ttl)
    finally:
        await r.close()


async def get_task_state(task_id: str) -> dict | None:
    """Retrieve task execution state."""
    r = _get_redis()
    try:
        key = f"task:{task_id}:state"
        data = await r.get(key)
        return json.loads(data) if data else None
    finally:
        await r.close()


async def update_task_status(task_id: str, status: str, metadata: dict | None = None) -> None:
    """Update just the status field of a task's state."""
    state = await get_task_state(task_id) or {}
    state["status"] = status
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    if metadata:
        state.update(metadata)
    await set_task_state(task_id, state)


# ── Agent state ───────────────────────────────────────────────────────────

async def set_agent_state(task_id: str, agent_name: str, state: dict, ttl: int = SESSION_TTL) -> None:
    """Store agent-specific intermediate state for a task."""
    r = _get_redis()
    try:
        key = f"task:{task_id}:agent:{agent_name}"
        await r.set(key, json.dumps(state, default=str), ex=ttl)
    finally:
        await r.close()


async def get_agent_state(task_id: str, agent_name: str) -> dict | None:
    """Retrieve agent-specific state."""
    r = _get_redis()
    try:
        key = f"task:{task_id}:agent:{agent_name}"
        data = await r.get(key)
        return json.loads(data) if data else None
    finally:
        await r.close()


# ── Session context ───────────────────────────────────────────────────────

async def set_session_context(session_id: str, data: dict, ttl: int = SESSION_TTL) -> None:
    """Store session-level context (spans multiple tasks)."""
    r = _get_redis()
    try:
        key = f"session:{session_id}:context"
        await r.set(key, json.dumps(data, default=str), ex=ttl)
    finally:
        await r.close()


async def get_session_context(session_id: str) -> dict | None:
    """Retrieve session-level context."""
    r = _get_redis()
    try:
        key = f"session:{session_id}:context"
        data = await r.get(key)
        return json.loads(data) if data else None
    finally:
        await r.close()


async def append_session_history(session_id: str, entry: dict, max_entries: int = 100) -> None:
    """Append an entry to session history (bounded list)."""
    r = _get_redis()
    try:
        key = f"session:{session_id}:history"
        await r.rpush(key, json.dumps(entry, default=str))
        await r.ltrim(key, -max_entries, -1)
        await r.expire(key, SESSION_TTL)
    finally:
        await r.close()


async def get_session_history(session_id: str, limit: int = 50) -> list[dict]:
    """Retrieve recent session history."""
    r = _get_redis()
    try:
        key = f"session:{session_id}:history"
        entries = await r.lrange(key, -limit, -1)
        return [json.loads(e) for e in entries]
    finally:
        await r.close()


# ── SSE subscriber tracking ──────────────────────────────────────────────

async def register_subscriber(task_id: str, subscriber_id: str) -> None:
    """Register an SSE subscriber for a task."""
    r = _get_redis()
    try:
        key = f"task:{task_id}:subscribers"
        await r.sadd(key, subscriber_id)
        await r.expire(key, SESSION_TTL)
    finally:
        await r.close()


async def remove_subscriber(task_id: str, subscriber_id: str) -> None:
    """Remove an SSE subscriber."""
    r = _get_redis()
    try:
        key = f"task:{task_id}:subscribers"
        await r.srem(key, subscriber_id)
    finally:
        await r.close()


async def get_subscriber_count(task_id: str) -> int:
    """Get number of active SSE subscribers for a task."""
    r = _get_redis()
    try:
        key = f"task:{task_id}:subscribers"
        return await r.scard(key)
    finally:
        await r.close()


# ── Cleanup ───────────────────────────────────────────────────────────────

async def cleanup_task(task_id: str) -> None:
    """Clean up all Redis keys for a completed task."""
    r = _get_redis()
    try:
        keys = []
        async for key in r.scan_iter(f"task:{task_id}:*"):
            keys.append(key)
        if keys:
            await r.delete(*keys)
            logger.debug("Cleaned up %d keys for task %s", len(keys), task_id)
    finally:
        await r.close()
