"""Server-Sent Events stream for real-time task updates."""

import asyncio
import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from config.settings import settings

router = APIRouter(prefix="/api/v1/tasks", tags=["stream"])


async def _event_generator(task_id: str, request: Request, last_event_id: str | None = None):
    """Yield SSE events from Redis Pub/Sub for a given task."""
    r = aioredis.from_url(settings.redis_url)
    pubsub = r.pubsub()
    channel = f"task:{task_id}:events"
    await pubsub.subscribe(channel)

    event_counter = 0
    skip_until = int(last_event_id) if last_event_id else 0

    try:
        while True:
            if await request.is_disconnected():
                break
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                event_counter += 1
                if event_counter <= skip_until:
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"id: {event_counter}\nevent: message\ndata: {data}\n\n"
            else:
                # Send keepalive comment every second
                yield ": keepalive\n\n"
                await asyncio.sleep(1)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await r.close()


@router.get("/{task_id}/stream")
async def stream_task(task_id: str, request: Request):
    """SSE endpoint for real-time task updates.

    Supports reconnection via the Last-Event-ID header.
    Each event: { type: "thought"|"action"|"result"|"error", content, agent, timestamp }
    """
    last_event_id = request.headers.get("Last-Event-ID")
    return StreamingResponse(
        _event_generator(task_id, request, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def publish_event(task_id: str, event_type: str, content: str, agent: str) -> None:
    """Publish an event to a task's Redis channel (called by agent workers)."""
    from datetime import datetime, timezone

    r = aioredis.from_url(settings.redis_url)
    payload = json.dumps({
        "type": event_type,
        "content": content,
        "agent": agent,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await r.publish(f"task:{task_id}:events", payload)
    await r.close()
