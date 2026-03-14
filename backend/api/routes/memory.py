"""Memory management endpoints — store and retrieve agent/task memory."""

import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Query

from api.schemas import MemoryEntry, MemoryStoreRequest
from config.settings import settings

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

_KEY_PREFIX = "memory:"


@router.post("", response_model=MemoryEntry, status_code=201)
async def store_memory(body: MemoryStoreRequest):
    """Store a memory entry (key-value with optional metadata)."""
    r = aioredis.from_url(settings.redis_url)
    try:
        entry_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "id": entry_id,
            "namespace": body.namespace,
            "key": body.key,
            "value": body.value,
            "metadata": body.metadata or {},
            "created_at": now,
        }
        # Store in a Redis hash keyed by namespace
        redis_key = f"{_KEY_PREFIX}{body.namespace}:{body.key}"
        await r.set(redis_key, json.dumps(entry))
        # Also index in a set for listing
        await r.sadd(f"{_KEY_PREFIX}{body.namespace}:_keys", body.key)
        return MemoryEntry(**entry)
    finally:
        await r.close()


@router.get("/{namespace}/{key}", response_model=MemoryEntry)
async def get_memory(namespace: str, key: str):
    """Retrieve a memory entry by namespace and key."""
    r = aioredis.from_url(settings.redis_url)
    try:
        redis_key = f"{_KEY_PREFIX}{namespace}:{key}"
        raw = await r.get(redis_key)
        if not raw:
            raise HTTPException(status_code=404, detail="Memory entry not found")
        return MemoryEntry(**json.loads(raw))
    finally:
        await r.close()


@router.get("/{namespace}", response_model=list[MemoryEntry])
async def list_memories(namespace: str, limit: int = Query(50, ge=1, le=500)):
    """List all memory entries in a namespace."""
    r = aioredis.from_url(settings.redis_url)
    try:
        keys = await r.smembers(f"{_KEY_PREFIX}{namespace}:_keys")
        entries = []
        for k in list(keys)[:limit]:
            key_str = k.decode("utf-8") if isinstance(k, bytes) else k
            raw = await r.get(f"{_KEY_PREFIX}{namespace}:{key_str}")
            if raw:
                entries.append(MemoryEntry(**json.loads(raw)))
        return entries
    finally:
        await r.close()


@router.delete("/{namespace}/{key}")
async def delete_memory(namespace: str, key: str):
    """Delete a memory entry."""
    r = aioredis.from_url(settings.redis_url)
    try:
        redis_key = f"{_KEY_PREFIX}{namespace}:{key}"
        deleted = await r.delete(redis_key)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory entry not found")
        await r.srem(f"{_KEY_PREFIX}{namespace}:_keys", key)
        return {"status": "deleted", "namespace": namespace, "key": key}
    finally:
        await r.close()
