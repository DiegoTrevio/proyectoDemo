"""Concurrency tests for SecureAgent SDK."""

import asyncio
import threading

import pytest

from secureagent import AuditLog, SecureAgent, TaintSource, TaintTracker
from secureagent.gates import ApprovalGate


class TestAuditConcurrency:
    def test_thread_safe_counter(self):
        """Multiple threads adding events should not produce duplicate IDs."""
        log = AuditLog()
        event_ids = []
        lock = threading.Lock()

        def add_events(thread_id: int):
            for i in range(100):
                hash_ = log.add_event(
                    session_id=f"thread_{thread_id}",
                    agent_id="agent",
                    action=f"action_{i}",
                )
                with lock:
                    event_ids.append(hash_)

        threads = [threading.Thread(target=add_events, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(event_ids) == 500
        # All hashes should be unique
        assert len(set(event_ids)) == 500

    @pytest.mark.asyncio
    async def test_concurrent_secure_calls(self):
        """100 concurrent secure_call should all succeed."""
        agent = SecureAgent(audit_log=True, taint_tracking=False, pii_detection=False)
        results = []

        async def mock_tool(index: int = 0):
            await asyncio.sleep(0.001)
            return f"result_{index}"

        tasks = [
            agent.secure_call(
                tool_name="search",
                tool_fn=mock_tool,
                args={"index": i},
                session_id="concurrent_test",
            )
            for i in range(100)
        ]
        results = await asyncio.gather(*tasks)
        assert len(results) == 100
        assert all(r.startswith("result_") for r in results)

        trail = agent.export_audit("concurrent_test")
        assert len(trail) == 100

    @pytest.mark.asyncio
    async def test_concurrent_sessions(self):
        """Multiple sessions writing simultaneously should be isolated."""
        log = AuditLog()

        async def write_session(session_id: str, count: int):
            for i in range(count):
                log.add_event(session_id=session_id, agent_id="agent", action=f"action_{i}")

        await asyncio.gather(
            write_session("sess_a", 50),
            write_session("sess_b", 30),
            write_session("sess_c", 20),
        )

        assert len(log.export_chain("sess_a")) == 50
        assert len(log.export_chain("sess_b")) == 30
        assert len(log.export_chain("sess_c")) == 20

        # Each chain should be valid
        for sess in ["sess_a", "sess_b", "sess_c"]:
            valid, _ = log.verify_chain(sess)
            assert valid


class TestTaintConcurrency:
    def test_concurrent_label_and_lookup(self):
        """Concurrent labeling and lookup should not crash."""
        tracker = TaintTracker()
        errors = []

        def label_content(thread_id: int):
            try:
                for i in range(100):
                    tracker.label(f"content_{thread_id}_{i}", TaintSource.WEB_SCRAPING)
            except Exception as e:
                errors.append(e)

        def lookup_content(thread_id: int):
            try:
                for i in range(100):
                    tracker.is_tainted(f"content_{thread_id}_{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for t in range(3):
            threads.append(threading.Thread(target=label_content, args=(t,)))
            threads.append(threading.Thread(target=lookup_content, args=(t,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestGatesConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_approval_checks(self):
        """Multiple concurrent approval checks should all complete."""
        async def approve_all(request):
            await asyncio.sleep(0.01)
            return True

        gate = ApprovalGate(
            risk_map={"tool_a": "high", "tool_b": "low"},
            approval_callback=approve_all,
        )

        tasks = []
        for i in range(50):
            tool = "tool_a" if i % 2 == 0 else "tool_b"
            tasks.append(gate.check(tool, session_id=f"sess_{i}"))

        results = await asyncio.gather(*tasks)
        assert all(results)
        assert gate.history_size == 50
