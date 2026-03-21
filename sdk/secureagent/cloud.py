"""Cloud Client — sends audit events to the SecureAgent Cloud dashboard.

Features:
- Circuit breaker pattern (CLOSED → OPEN → HALF_OPEN)
- Exponential backoff with jitter
- Bounded buffer with overflow warning
- Graceful shutdown with flush
"""

import asyncio
import json
import logging
import random
import time
from collections import deque
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("secureagent.cloud")


class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, skip calls
    HALF_OPEN = "half_open"  # Test one call


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time: float = 0.0

    def record_success(self) -> None:
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker: HALF_OPEN → CLOSED (recovered)")
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    "Circuit breaker: → OPEN after %d consecutive failures",
                    self.failure_count,
                )
            self.state = CircuitState.OPEN

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker: OPEN → HALF_OPEN (testing)")
                return True
            return False
        # HALF_OPEN: allow one request
        return True


class CloudClient:
    """Sends events to SecureAgent Cloud for dashboard visualization.

    Usage:
        client = CloudClient(api_key="sk-...")

        # Send a single event (non-blocking, queued)
        client.send_event({"type": "tool_call", "tool": "search", ...})

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
        max_buffer_size: int = 5000,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
    ):
        self._api_key = api_key
        self._base_url = (base_url or self.CLOUD_URL).rstrip("/")
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_buffer_size)
        self._max_buffer_size = max_buffer_size
        self._flush_task: Optional[asyncio.Task] = None
        self._closed = False
        self._client = None
        self._circuit = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_timeout,
        )
        self._events_sent = 0
        self._events_dropped = 0

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

        # Check if circuit breaker is open
        if not self._circuit.allow_request():
            logger.debug("Circuit open — event queued but send skipped")

        # Warn if buffer is getting full
        buffer_usage = len(self._buffer) / self._max_buffer_size
        if buffer_usage > 0.8 and len(self._buffer) % 100 == 0:
            logger.warning(
                "Cloud buffer %.0f%% full (%d/%d events)",
                buffer_usage * 100, len(self._buffer), self._max_buffer_size,
            )

        was_full = len(self._buffer) >= self._max_buffer_size
        event["_ts"] = time.time()
        self._buffer.append(event)  # deque maxlen auto-evicts oldest

        if was_full:
            self._events_dropped += 1
            if self._events_dropped % 100 == 1:
                logger.warning(
                    "Cloud buffer full — dropped %d oldest events total",
                    self._events_dropped,
                )

        if len(self._buffer) >= self._batch_size:
            try:
                asyncio.ensure_future(self.flush())
            except RuntimeError:
                pass  # No event loop running

    async def flush(self) -> bool:
        """Send all buffered events to the cloud."""
        if not self._buffer:
            return True

        if not self._circuit.allow_request():
            logger.debug("Circuit open — flush skipped")
            return False

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
                    self._circuit.record_success()
                    self._events_sent += len(batch)
                    logger.debug("Flushed %d events to cloud (total: %d)", len(batch), self._events_sent)
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

            self._circuit.record_failure()

            if attempt < self._max_retries - 1:
                # Exponential backoff with jitter (±30%)
                base_delay = 2 ** attempt  # 1, 2, 4
                jitter = base_delay * random.uniform(-0.3, 0.3)
                delay = max(0.1, base_delay + jitter)
                await asyncio.sleep(delay)

        # Re-queue failed events (prepend back to buffer)
        for event in reversed(batch):
            if len(self._buffer) < self._max_buffer_size:
                self._buffer.appendleft(event)
            else:
                self._events_dropped += 1

        logger.error("Failed to flush %d events after %d retries", len(batch), self._max_retries)
        return False

    async def start_auto_flush(self) -> None:
        """Start background task that flushes events periodically."""
        async def _flush_loop():
            while not self._closed:
                await asyncio.sleep(self._flush_interval)
                if self._buffer and self._circuit.allow_request():
                    await self.flush()

        self._flush_task = asyncio.create_task(_flush_loop())

    async def close(self) -> None:
        """Flush remaining events and close the client."""
        self._closed = True
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush attempt
        while self._buffer and self._circuit.allow_request():
            await self.flush()
        if self._client:
            await self._client.aclose()
        logger.info(
            "Cloud client closed: %d sent, %d dropped",
            self._events_sent, self._events_dropped,
        )

    def get_stats(self) -> dict:
        """Get cloud client statistics."""
        return {
            "buffer_size": len(self._buffer),
            "buffer_capacity": self._max_buffer_size,
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
            "circuit_state": self._circuit.state.value,
            "circuit_failures": self._circuit.failure_count,
        }
