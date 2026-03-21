"""Tests for the Cloud Client module."""

import asyncio
import pytest

from secureagent.cloud import CircuitBreaker, CircuitState, CloudClient


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow_request()

    def test_success_resets_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        import time
        time.sleep(0.15)

        assert cb.allow_request()
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        cb.allow_request()  # Triggers HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        cb.allow_request()  # HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCloudClient:
    def test_send_event_queues(self):
        client = CloudClient(api_key="test-key", max_buffer_size=100)
        client.send_event({"type": "test"})
        assert len(client._buffer) == 1

    def test_buffer_bounded(self):
        client = CloudClient(api_key="test-key", max_buffer_size=10)
        for i in range(20):
            client.send_event({"type": f"test_{i}"})
        assert len(client._buffer) == 10

    def test_closed_client_ignores_events(self):
        client = CloudClient(api_key="test-key")
        client._closed = True
        client.send_event({"type": "test"})
        assert len(client._buffer) == 0

    def test_get_stats(self):
        client = CloudClient(api_key="test-key")
        client.send_event({"type": "test"})
        stats = client.get_stats()
        assert stats["buffer_size"] == 1
        assert stats["events_sent"] == 0
        assert stats["circuit_state"] == "closed"

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self):
        client = CloudClient(api_key="test-key")
        result = await client.flush()
        assert result is True

    @pytest.mark.asyncio
    async def test_close_sets_flag(self):
        client = CloudClient(api_key="test-key", base_url="http://localhost:9999")
        client.send_event({"type": "test"})
        # Close will try to flush but fail (no server) — should not raise
        await client.close()
        assert client._closed is True
