"""OpenClaw Bridge — connects AgentOS to WhatsApp/Telegram via OpenClaw.

Flow:
  1. User sends message via WhatsApp → OpenClaw webhook
  2. POST /api/v1/openclaw/webhook receives it
  3. Creates task and launches orchestrator
  4. Subscribes to SSE stream for progress updates
  5. Sends partial updates every 30s to user's chat
  6. Delivers final result (text, file attachment, or image)
  7. Handles approval gates by forwarding questions to chat
"""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from config.settings import settings

logger = logging.getLogger("agentos.integrations.openclaw")


OPENCLAW_API_URL = "https://api.openclaw.ai/v1"
UPDATE_INTERVAL = 30  # seconds between partial updates


class OpenClawBridge:
    """Manages OpenClaw webhook and message delivery."""

    def __init__(self, webhook_secret: str = ""):
        self.webhook_secret = webhook_secret

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify OpenClaw webhook signature."""
        if not self.webhook_secret:
            return True  # No secret configured — skip verification

        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    @staticmethod
    def parse_webhook(data: dict) -> dict:
        """Parse incoming OpenClaw webhook into a task request.

        Returns dict with: user_id, goal, channel, message_id, reply_to
        """
        return {
            "user_id": data.get("from", {}).get("id", ""),
            "goal": data.get("message", {}).get("text", ""),
            "channel": data.get("channel", "whatsapp"),
            "message_id": data.get("message_id", ""),
            "reply_to": data.get("reply_to", ""),
            "phone": data.get("from", {}).get("phone", ""),
        }

    @staticmethod
    async def send_message(
        user_id: str,
        text: str,
        channel: str = "whatsapp",
    ) -> bool:
        """Send a text message to the user via OpenClaw."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{OPENCLAW_API_URL}/messages",
                    json={
                        "to": user_id,
                        "channel": channel,
                        "type": "text",
                        "text": text[:4000],  # WhatsApp limit
                    },
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("Failed to send OpenClaw message: %s", e)
            return False

    @staticmethod
    async def send_file(
        user_id: str,
        file_url: str,
        filename: str,
        mime_type: str,
        channel: str = "whatsapp",
    ) -> bool:
        """Send a file attachment to the user via OpenClaw."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{OPENCLAW_API_URL}/messages",
                    json={
                        "to": user_id,
                        "channel": channel,
                        "type": "document",
                        "document": {
                            "url": file_url,
                            "filename": filename,
                            "mime_type": mime_type,
                        },
                    },
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("Failed to send OpenClaw file: %s", e)
            return False

    async def handle_task_stream(
        self,
        task_id: str,
        user_id: str,
        channel: str = "whatsapp",
    ) -> None:
        """Subscribe to task SSE stream and forward updates to user's chat.

        Sends partial updates every 30 seconds and the final result when done.
        """
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        pubsub = r.pubsub()

        try:
            await pubsub.subscribe(f"task:{task_id}:events")

            last_update = datetime.now(timezone.utc)
            collected_updates: list[str] = []
            task_done = False

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    event = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                event_type = event.get("type", "")
                content = event.get("content", "")

                # Handle approval requests
                if event_type == "approval_required":
                    approval_text = (
                        f"I need your approval:\n\n"
                        f"*{event.get('action', '')}*\n"
                        f"{event.get('reason', '')}\n\n"
                        f"Reply 'yes' to approve or 'no' to reject.\n"
                        f"(Auto-rejects in 5 minutes)"
                    )
                    await self.send_message(user_id, approval_text, channel)
                    continue

                # Collect updates
                if event_type in ("thought", "action", "result"):
                    collected_updates.append(f"{event_type}: {content[:200]}")

                # Check for completion
                if event_type == "result" and "Task completed" in content:
                    task_done = True

                # Send periodic updates
                now = datetime.now(timezone.utc)
                elapsed = (now - last_update).total_seconds()

                if elapsed >= UPDATE_INTERVAL and collected_updates:
                    summary = "\n".join(collected_updates[-3:])  # Last 3 updates
                    await self.send_message(
                        user_id,
                        f"Working on it...\n\n{summary}",
                        channel,
                    )
                    collected_updates.clear()
                    last_update = now

                if task_done:
                    # Send final result
                    await self.send_message(
                        user_id,
                        f"Done! Here's the result:\n\n{content[:3500]}",
                        channel,
                    )
                    break

        except Exception as e:
            logger.error("Task stream handling failed: %s", e)
            await self.send_message(
                user_id,
                f"Sorry, something went wrong. Please try again.",
                channel,
            )
        finally:
            await pubsub.unsubscribe()
            await r.close()


# Singleton
openclaw_bridge = OpenClawBridge()


# ── FastAPI router ───────────────────────────────────────────────────────

def create_openclaw_router():
    """Create FastAPI router for OpenClaw webhook endpoints."""
    from fastapi import APIRouter, Request, HTTPException

    router = APIRouter(prefix="/api/v1/openclaw", tags=["openclaw"])

    @router.post("/webhook")
    async def openclaw_webhook(request: Request):
        """Receive messages from OpenClaw (WhatsApp/Telegram)."""
        body = await request.body()
        signature = request.headers.get("X-OpenClaw-Signature", "")

        if not openclaw_bridge.verify_signature(body, signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

        data = json.loads(body)
        parsed = openclaw_bridge.parse_webhook(data)

        if not parsed["goal"]:
            return {"status": "ignored", "reason": "empty message"}

        # Check if this is an approval response
        goal_lower = parsed["goal"].strip().lower()
        if goal_lower in ("yes", "no", "approve", "reject"):
            # Route to approval handler
            return {"status": "approval_response", "approved": goal_lower in ("yes", "approve")}

        # Create task
        try:
            from agents.orchestrator import run_task
            task_id = f"oc_{parsed['message_id'] or 'unknown'}"

            # Send acknowledgment
            await openclaw_bridge.send_message(
                parsed["user_id"],
                f"Got it! Working on: {parsed['goal'][:200]}...",
                parsed["channel"],
            )

            # Launch task in background
            asyncio.create_task(
                _run_and_stream(task_id, parsed)
            )

            return {"status": "accepted", "task_id": task_id}
        except Exception as e:
            logger.exception("OpenClaw task creation failed")
            raise HTTPException(status_code=500, detail=str(e))

    return router


async def _run_and_stream(task_id: str, parsed: dict):
    """Run orchestrator and stream results to OpenClaw user."""
    from agents.orchestrator import run_task

    # Start streaming in parallel with task execution
    stream_task = asyncio.create_task(
        openclaw_bridge.handle_task_stream(
            task_id, parsed["user_id"], parsed["channel"],
        )
    )

    try:
        await run_task(
            task_id=task_id,
            goal=parsed["goal"],
            config={"user_id": parsed["user_id"], "channel": parsed["channel"]},
        )
    except Exception as e:
        logger.error("OpenClaw task failed: %s", e)
        await openclaw_bridge.send_message(
            parsed["user_id"],
            f"Task failed: {str(e)[:500]}",
            parsed["channel"],
        )

    # Wait for stream to finish
    try:
        await asyncio.wait_for(stream_task, timeout=10)
    except asyncio.TimeoutError:
        pass
