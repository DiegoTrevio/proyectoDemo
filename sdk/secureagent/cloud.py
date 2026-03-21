"""Cloud Client — sends audit events to the SecureAgent Cloud dashboard.

Batches events and sends them asynchronously to minimize latency impact.
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Optional

logger = logging.getLogger("secureagent.cloud")


class CloudClient:
    """Sends events to SecureAgent Cloud for dashboard visualization.

    Usage:
        client = CloudClient(api_key="sk-...")

        # Send a single event
        await client.send_event({
            "type": "tool_call",
            "tool": "send_email",
            "risk": "high",
            ...
        })

        # Flush pending events
        await client.flush()

        # Close (flushes remaining)
        await client.close()
    """

    CLOUD_URL = "https://api.secureagent.dev/v1/ingest"

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        batch_size: int = 50,
        flush_interval: float = 5.0,
        max_retries: int = 3,
    ):
        self._api_key = api_key
        self._base_url = (base_url or self.CLOUD_URL).rstrip("/")
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._buffer: deque[dict[str, Any]] = deque(maxlen=10000)
        self._flush_task: Optional[asyncio.Task] = None
        self._closed = False
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "secureagent-sdk/0.1.0",
                },
                timeout=10.0,
            )
        return self._client

    def send_event(self, event: dict[str, Any]) -> None:
        """Queue an event for sending. Non-blocking."""
        if self._closed:
            return
        event["_ts"] = time.time()
        self._buffer.append(event)

        if len(self._buffer) >= self._batch_size:
            asyncio.ensure_future(self.flush())

    async def flush(self) -> bool:
        """Send all buffered events to the cloud."""
        if not self._buffer:
            return True

        batch = []
        while self._buffer and len(batch) < self._batch_size:
            batch.append(self._buffer.popleft())

        if not batch:
            return True

        client = await self._get_client()
        payload = json.dumps({"events": batch})

        for attempt in range(self._max_retries):
            try:
                response = await client.post(f"{self._base_url}", content=payload)
                if response.status_code in (200, 201, 202):
                    logger.debug("Flushed %d events to cloud", len(batch))
                    return True
                logger.warning(
                    "Cloud API returned %d (attempt %d/%d)",
                    response.status_code, attempt + 1, self._max_retries,
                )
            except Exception as e:
                logger.warning(
                    "Cloud send failed (attempt %d/%d): %s",
                    attempt + 1, self._max_retries, e,
                )

            if attempt < self._max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        # Re-queue failed events
        for event in reversed(batch):
            self._buffer.appendleft(event)
        logger.error("Failed to flush %d events after %d retries", len(batch), self._max_retries)
        return False

    async def start_auto_flush(self) -> None:
        """Start background task that flushes events periodically."""
        async def _flush_loop():
            while not self._closed:
                await asyncio.sleep(self._flush_interval)
                if self._buffer:
                    await self.flush()

        self._flush_task = asyncio.create_task(_flush_loop())

    async def close(self) -> None:
        """Flush remaining events and close the client."""
        self._closed = True
        if self._flush_task:
            self._flush_task.cancel()
        await self.flush()
        if self._client:
            await self._client.aclose()
