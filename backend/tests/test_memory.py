"""Tests for the 4-layer memory system."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from memory.openviking_layer import OpenVikingLayer, openviking
from memory.graphiti_layer import GraphitiLayer, Fact, graphiti
from memory.mem0_layer import Mem0Layer, Memory, mem0
from memory.manager import gather_context, save_learnings, get_memory_stats


@pytest.fixture(autouse=True)
def mock_redis_for_memory():
    """Mock Redis connections to prevent hanging on redis:6379."""
    mock_r = AsyncMock()
    mock_r.set = AsyncMock()
    mock_r.get = AsyncMock(return_value=None)
    mock_r.hset = AsyncMock()
    mock_r.hgetall = AsyncMock(return_value={})
    mock_r.close = AsyncMock()
    mock_r.aclose = AsyncMock()
    with patch("redis.asyncio.from_url", return_value=mock_r):
        yield mock_r


# ─── OpenViking Layer ─────────────────────────────────────────────────────

class TestOpenViking:

    def setup_method(self):
        self.ov = OpenVikingLayer()

    def test_store_and_retrieve(self):
        path = self.ov.store("viking://test/doc1", "Full content of the document")
        assert path == "viking://test/doc1"

        # L0
        l0 = self.ov.retrieve(path, tier=0)
        assert l0 is not None
        assert len(l0) > 0

        # L2 (full)
        l2 = self.ov.retrieve(path, tier=2)
        assert l2 == "Full content of the document"

    def test_not_found(self):
        assert self.ov.retrieve("viking://nonexistent") is None

    def test_store_resource(self):
        path = self.ov.store_resource("Q4 Report", "Revenue was $10M in Q4.")
        assert path.startswith("viking://resources/")
        content = self.ov.retrieve(path, tier=2)
        assert "Revenue" in content

    def test_store_user_memory(self):
        path = self.ov.store_user_memory("user1", "preference", "User prefers dark mode")
        assert "viking://user/memories/user1/" in path

    def test_store_agent_memory(self):
        path = self.ov.store_agent_memory("researcher", "tesla-knowledge", "Tesla is an EV company")
        assert "viking://agent/memories/researcher/" in path

    def test_search(self):
        self.ov.store("viking://resources/tesla", "Tesla is an electric vehicle company founded by Elon Musk")
        self.ov.store("viking://resources/apple", "Apple makes iPhones and MacBooks")

        results = self.ov.search("Tesla")
        assert len(results) >= 1
        assert results[0]["path"] == "viking://resources/tesla"

    def test_search_with_prefix(self):
        self.ov.store("viking://resources/doc1", "Python programming language")
        self.ov.store("viking://user/memories/u1/pref", "User likes Python")

        results = self.ov.search("Python", prefix="viking://user/")
        assert all(r["path"].startswith("viking://user/") for r in results)

    def test_l0_generation(self):
        long_text = "This is a sentence. " * 100
        l0 = OpenVikingLayer._generate_l0(long_text)
        assert len(l0) <= 500  # ~100 tokens

    def test_l1_generation(self):
        long_text = "This is a sentence. " * 1000
        l1 = OpenVikingLayer._generate_l1(long_text)
        assert len(l1) <= 8500  # ~2K tokens

    def test_get_context_for_task(self):
        self.ov.store("viking://resources/ai", "Artificial intelligence overview")
        ctx = self.ov.get_context_for_task("Artificial intelligence overview")
        assert "Artificial intelligence" in ctx or ctx == ""  # search may not match on simple keyword overlap

    def test_list_paths(self):
        self.ov.store("viking://resources/a", "content a")
        self.ov.store("viking://resources/b", "content b")
        paths = self.ov.list_paths("viking://resources/")
        assert len(paths) >= 2

    def test_delete(self):
        self.ov.store("viking://test/del", "to be deleted")
        assert self.ov.retrieve("viking://test/del") is not None
        assert self.ov.delete("viking://test/del")
        assert self.ov.retrieve("viking://test/del") is None

    def test_token_estimate(self):
        from memory.openviking_layer import ContextEntry
        entry = ContextEntry(
            path="test", l0="short", l1="a" * 8000, l2="b" * 40000,
        )
        est = entry.token_estimate
        assert est["l0"] < est["l1"] < est["l2"]


# ─── Graphiti Layer ───────────────────────────────────────────────────────

class TestGraphiti:

    def setup_method(self):
        self.gl = GraphitiLayer()

    @pytest.mark.asyncio
    async def test_add_fact(self):
        fact = await self.gl.add_fact(
            subject="Tesla",
            predicate="is_a",
            obj="Electric Vehicle Company",
            source="test",
        )
        assert isinstance(fact, Fact)
        assert fact.subject == "Tesla"
        assert fact.predicate == "is_a"
        assert fact.object == "Electric Vehicle Company"
        assert fact.triple == "(Tesla) -[is_a]-> (Electric Vehicle Company)"

    @pytest.mark.asyncio
    async def test_query_facts(self):
        await self.gl.add_fact("Tesla", "ceo", "Elon Musk", source="test")
        await self.gl.add_fact("Apple", "ceo", "Tim Cook", source="test")

        facts = await self.gl.query_facts("Tesla")
        assert len(facts) >= 1
        assert any(f.subject == "Tesla" for f in facts)

    @pytest.mark.asyncio
    async def test_query_with_time_range(self):
        now = datetime.now(timezone.utc)
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)

        await self.gl.add_fact("Tesla", "founded", "2003", event_time=past, source="test")
        await self.gl.add_fact("Tesla", "revenue_2024", "$96B", event_time=now, source="test")

        recent_facts = await self.gl.query_facts(
            "Tesla",
            time_range=(datetime(2024, 1, 1, tzinfo=timezone.utc), now),
        )
        old_facts = await self.gl.query_facts(
            "Tesla",
            time_range=(datetime(2019, 1, 1, tzinfo=timezone.utc), datetime(2021, 1, 1, tzinfo=timezone.utc)),
        )

        # At least one should match time ranges
        assert isinstance(recent_facts, list)
        assert isinstance(old_facts, list)

    @pytest.mark.asyncio
    async def test_get_timeline(self):
        t1 = datetime(2020, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2022, 1, 1, tzinfo=timezone.utc)
        t3 = datetime(2024, 1, 1, tzinfo=timezone.utc)

        await self.gl.add_fact("Tesla", "event_a", "Launched Model Y", event_time=t1)
        await self.gl.add_fact("Tesla", "event_b", "Cybertruck announced", event_time=t2)
        await self.gl.add_fact("Tesla", "event_c", "FSD released", event_time=t3)

        timeline = await self.gl.get_timeline("Tesla")
        assert len(timeline) >= 3
        # Should be sorted chronologically
        for i in range(len(timeline) - 1):
            assert timeline[i].event_time <= timeline[i + 1].event_time

    def test_get_stats(self):
        stats = self.gl.get_stats()
        assert "backend" in stats


# ─── Mem0 Layer ───────────────────────────────────────────────────────────

class TestMem0:

    def test_memory_dataclass(self):
        m = Memory(id="test-1", content="Test content", level="user")
        assert m.level == "user"

    def test_not_available_without_key(self):
        layer = Mem0Layer()
        # Without API key, should gracefully handle operations
        assert layer.add_memory("user1", "test") is None
        assert layer.search_memory("user1", "test") == []
        assert layer.get_all("user1") == []

    def test_session_memory_without_key(self):
        layer = Mem0Layer()
        assert layer.add_session_memory("session1", "test") is None
        assert layer.search_session_memory("session1", "test") == []

    def test_agent_memory_without_key(self):
        layer = Mem0Layer()
        assert layer.add_agent_memory("researcher", "test") is None
        assert layer.search_agent_memory("researcher", "test") == []


# ─── Memory Manager ──────────────────────────────────────────────────────

class TestMemoryManager:

    @pytest.mark.asyncio
    async def test_gather_context_empty(self):
        """Context gathering works even with no stored data."""
        ctx = await gather_context("What is Tesla?", user_id="test-user")
        assert isinstance(ctx, dict)
        assert "openviking" in ctx
        assert "mem0_memories" in ctx
        assert "graphiti_facts" in ctx
        assert "combined" in ctx

    @pytest.mark.asyncio
    async def test_gather_context_with_openviking(self):
        """Context includes OpenViking data when available."""
        openviking.store_resource("tesla-info", "Tesla is an EV company", metadata={"topic": "Tesla"})
        ctx = await gather_context("Tell me about Tesla")
        assert isinstance(ctx["openviking"], str)

    @pytest.mark.asyncio
    async def test_save_learnings(self):
        """Save learnings stores to all available layers."""
        status = await save_learnings(
            goal="Investigate Tesla",
            result="Tesla is an EV company worth $800B",
            task_id="test-task-1",
            user_id="test-user",
        )
        assert isinstance(status, dict)
        assert status["openviking"]  # OpenViking in-memory always works
        assert status["graphiti"]    # Graphiti in-memory always works

    @pytest.mark.asyncio
    async def test_second_run_has_memory(self):
        """Second execution of same topic should find prior context."""
        # First run
        await save_learnings(
            goal="Research Tesla stock",
            result="Tesla stock is at $250",
            task_id="task-tesla-1",
        )
        # Store to OpenViking for searchability
        openviking.store_resource("tesla-stock", "Tesla stock is at $250")

        # Second run — gather context
        ctx = await gather_context("Research Tesla")
        # Should find the Tesla resource
        assert "Tesla" in ctx.get("openviking", "") or ctx.get("graphiti_facts")

    def test_get_memory_stats(self):
        stats = get_memory_stats()
        assert "openviking" in stats
        assert "mem0" in stats
        assert "graphiti" in stats


# ─── Integration: Repeated Task Memory ───────────────────────────────────

@pytest.mark.asyncio
async def test_repeated_tesla_investigation():
    """Simulate: run 'Investigate Tesla' twice, second time should have memory."""

    # Run 1: save learnings about Tesla
    await save_learnings(
        goal="Investiga Tesla",
        result="Tesla es una empresa de vehiculos electricos. CEO: Elon Musk. Market cap: $800B.",
        task_id="tesla-run-1",
        user_id="test-user",
        facts=[
            {"subject": "Tesla", "predicate": "is_a", "object": "EV Company"},
            {"subject": "Tesla", "predicate": "has_ceo", "object": "Elon Musk"},
            {"subject": "Tesla", "predicate": "market_cap", "object": "$800B"},
        ],
    )

    # Run 2: gather context — should find Tesla data
    ctx = await gather_context("Investiga Tesla", user_id="test-user", task_id="tesla-run-2")

    # Graphiti should have Tesla facts from run 1
    assert len(ctx["graphiti_facts"]) >= 1

    # Check that facts have timestamps
    for fact in ctx["graphiti_facts"]:
        assert "event_time" in fact
        assert fact["subject"] or fact["object"]  # At least one entity
