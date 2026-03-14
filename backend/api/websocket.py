"""WebSocket handler for bidirectional human-in-the-loop communication."""

import asyncio
import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config.settings import settings

router = APIRouter()


@router.websocket("/ws/tasks/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str):
    """Bidirectional WebSocket for task interaction.

    - Server → Client: agent events (thought, action, result, error, confirm_request)
    - Client → Server: user messages, confirmations
    """
    await websocket.accept()

    r = aioredis.from_url(settings.redis_url)
    pubsub = r.pubsub()
    channel = f"task:{task_id}:events"
    user_channel = f"task:{task_id}:user_input"
    await pubsub.subscribe(channel)

    async def _forward_events():
        """Forward Redis events to the WebSocket client."""
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    await websocket.send_text(data)
                else:
                    await asyncio.sleep(0.1)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    forward_task = asyncio.create_task(_forward_events())

    try:
        while True:
            raw = await websocket.receive_text()
            # Publish user input so agents can consume it
            payload = json.dumps({
                "type": "user_message",
                "content": raw,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await r.publish(user_channel, payload)
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await r.close()
