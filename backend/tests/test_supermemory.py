"""Tests for Supermemory integration — layer, manager, and MCP."""

import os

os.environ["TESTING"] = "1"

from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

from memory.supermemory_layer import SupermemoryLayer, SupermemoryEntry, UserProfile


@pytest.fixture(autouse=True)
def mock_redis_for_supermemory():
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


# ─── SupermemoryLayer unit tests ─────────────────────────────────────────────


class TestSupermemoryLayer:
    """Test SupermemoryLayer with mocked SDK client."""

    def _make_layer(self) -> SupermemoryLayer:
        """Create a layer with a mocked Supermemory client."""
        layer = SupermemoryLayer.__new__(SupermemoryLayer)
        layer._client = MagicMock()
        layer._async_client = None
        return layer

    def test_available_when_client_set(self):
        layer = self._make_layer()
        assert layer.available is True

    def test_unavailable_when_no_client(self):
        layer = SupermemoryLayer.__new__(SupermemoryLayer)
        layer._client = None
        layer._async_client = None
        assert layer.available is False

    def test_container_tags(self):
        assert SupermemoryLayer._user_tag("alice") == "user_alice"
        assert SupermemoryLayer._session_tag("s-001") == "session_s-001"
        assert SupermemoryLayer._agent_tag("researcher") == "agent_researcher"

    def test_add_memory_calls_client(self):
        layer = self._make_layer()
        layer._client.add.return_value = MagicMock(id="mem-001")

        result = layer.add_memory("user1", "Prefers dark mode", metadata={"cat": "pref"})

        assert result is not None
        layer._client.add.assert_called_once_with(
            content="Prefers dark mode",
            container_tags=["user_user1"],
            metadata={"level": "user", "cat": "pref"},
        )

    def test_add_memory_returns_none_when_unavailable(self):
        layer = SupermemoryLayer.__new__(SupermemoryLayer)
        layer._client = None
        layer._async_client = None
        assert layer.add_memory("u1", "test") is None

    def test_search_memory_parses_results(self):
        layer = self._make_layer()
        mock_entry = MagicMock()
        mock_entry.id = "e-001"
        mock_entry.content = "Likes Python"
        mock_entry.metadata = {"level": "user"}
        mock_entry.score = 0.95

        mock_results = MagicMock()
        mock_results.results = [mock_entry]
        layer._client.search.memories.return_value = mock_results

        entries = layer.search_memory("user1", "programming preferences")

        assert len(entries) == 1
        assert entries[0].content == "Likes Python"
        assert entries[0].score == 0.95
        assert entries[0].level == "user"

    def test_search_memory_empty_when_unavailable(self):
        layer = SupermemoryLayer.__new__(SupermemoryLayer)
        layer._client = None
        layer._async_client = None
        assert layer.search_memory("u1", "q") == []

    def test_get_profile_returns_static_and_dynamic(self):
        layer = self._make_layer()
        mock_profile = MagicMock()
        mock_profile.profile.static = ["Senior engineer", "Uses Vim"]
        mock_profile.profile.dynamic = ["Working on auth migration"]
        layer._client.profile.return_value = mock_profile

        profile = layer.get_profile("user1", query="background")

        assert profile.static == ["Senior engineer", "Uses Vim"]
        assert profile.dynamic == ["Working on auth migration"]
        layer._client.profile.assert_called_once_with(
            container_tag="user_user1",
            q="background",
        )

    def test_get_profile_empty_when_unavailable(self):
        layer = SupermemoryLayer.__new__(SupermemoryLayer)
        layer._client = None
        layer._async_client = None
        profile = layer.get_profile("u1")
        assert profile.static == []
        assert profile.dynamic == []

    def test_add_session_memory(self):
        layer = self._make_layer()
        layer._client.add.return_value = MagicMock(id="sess-mem-001")

        result = layer.add_session_memory("s-001", "Decided to use React")

        assert result is not None
        layer._client.add.assert_called_once_with(
            content="Decided to use React",
            container_tags=["session_s-001"],
            metadata={"level": "session"},
        )

    def test_add_agent_memory(self):
        layer = self._make_layer()
        layer._client.add.return_value = MagicMock(id="agent-mem-001")

        result = layer.add_agent_memory("researcher", "Good at summarizing papers")

        assert result is not None
        layer._client.add.assert_called_once_with(
            content="Good at summarizing papers",
            container_tags=["agent_researcher"],
            metadata={"level": "agent"},
        )

    def test_extract_and_store(self):
        layer = self._make_layer()
        layer._client.add.return_value = MagicMock(id="conv-001")

        conversation = [
            {"role": "user", "content": "My name is Alice"},
            {"role": "assistant", "content": "Nice to meet you, Alice!"},
        ]

        ids = layer.extract_and_store("user1", conversation, session_id="s-001")

        assert len(ids) == 1
        call_kwargs = layer._client.add.call_args
        assert "user_user1" in call_kwargs.kwargs["container_tags"]
        assert "session_s-001" in call_kwargs.kwargs["container_tags"]
        assert "Alice" in call_kwargs.kwargs["content"]

    def test_search_handles_sdk_exception(self):
        layer = self._make_layer()
        layer._client.search.memories.side_effect = Exception("Network error")

        entries = layer.search_memory("user1", "test query")
        assert entries == []

    def test_get_profile_handles_sdk_exception(self):
        layer = self._make_layer()
        layer._client.profile.side_effect = Exception("API error")

        profile = layer.get_profile("user1")
        assert profile.static == []
        assert profile.dynamic == []


# ─── Async variants ──────────────────────────────────────────────────────────


class TestSupermemoryAsync:
    """Test async methods fall back to sync when no async client."""

    @pytest.mark.asyncio
    async def test_async_search_falls_back_to_sync(self):
        layer = SupermemoryLayer.__new__(SupermemoryLayer)
        layer._client = MagicMock()
        layer._async_client = None

        mock_entry = MagicMock()
        mock_entry.id = "e-001"
        mock_entry.content = "Test memory"
        mock_entry.metadata = {}
        mock_entry.score = 0.8
        mock_results = MagicMock()
        mock_results.results = [mock_entry]
        layer._client.search.memories.return_value = mock_results

        entries = await layer.async_search_memory("user1", "test")

        assert len(entries) == 1
        assert entries[0].content == "Test memory"

    @pytest.mark.asyncio
    async def test_async_profile_falls_back_to_sync(self):
        layer = SupermemoryLayer.__new__(SupermemoryLayer)
        layer._client = MagicMock()
        layer._async_client = None

        mock_profile = MagicMock()
        mock_profile.profile.static = ["Fact 1"]
        mock_profile.profile.dynamic = ["Recent 1"]
        layer._client.profile.return_value = mock_profile

        profile = await layer.async_get_profile("user1")

        assert profile.static == ["Fact 1"]
        assert profile.dynamic == ["Recent 1"]


# ─── Memory Manager integration ─────────────────────────────────────────────


class TestManagerSupermemoryIntegration:
    """Test that the memory manager uses Supermemory as primary L1."""

    @pytest.mark.asyncio
    async def test_gather_context_prefers_supermemory_over_mem0(self):
        """When Supermemory returns results, Mem0 should not be called."""
        mock_entry = SupermemoryEntry(id="e1", content="Supermemory result", score=0.9)

        with patch("memory.manager.supermemory_client") as mock_sm, \
             patch("memory.manager.mem0") as mock_mem0, \
             patch("memory.manager.openviking") as mock_ov, \
             patch("memory.manager.graphiti") as mock_graphiti:

            mock_sm.available = True
            mock_sm.async_search_memory = AsyncMock(return_value=[mock_entry])
            mock_sm.async_get_profile = AsyncMock(return_value=UserProfile(
                static=["Engineer"], dynamic=["Working on auth"],
            ))
            mock_ov.get_context_for_task.return_value = ""
            mock_graphiti.query_facts = AsyncMock(return_value=[])

            from memory.manager import gather_context
            ctx = await gather_context("test goal", user_id="u1")

            # Supermemory was called
            mock_sm.async_search_memory.assert_called_once()
            # Mem0 was NOT called (Supermemory succeeded)
            mock_mem0.search_memory.assert_not_called()
            # Results contain Supermemory data
            assert any("Supermemory result" in m["content"] for m in ctx["supermemory_memories"])
            assert ctx["user_profile"]["static"] == ["Engineer"]

    @pytest.mark.asyncio
    async def test_gather_context_falls_back_to_mem0(self):
        """When Supermemory is unavailable, Mem0 should be used."""
        from memory.mem0_layer import Memory

        with patch("memory.manager.supermemory_client") as mock_sm, \
             patch("memory.manager.mem0") as mock_mem0, \
             patch("memory.manager.openviking") as mock_ov, \
             patch("memory.manager.graphiti") as mock_graphiti:

            mock_sm.available = False
            mock_ov.get_context_for_task.return_value = ""
            mock_graphiti.query_facts = AsyncMock(return_value=[])
            mock_mem0.search_memory.return_value = [
                Memory(id="m1", content="Mem0 fallback result", score=0.7),
            ]

            from memory.manager import gather_context
            ctx = await gather_context("test goal", user_id="u1")

            # Mem0 was called as fallback
            mock_mem0.search_memory.assert_called_once()
            assert any("Mem0 fallback" in m["content"] for m in ctx["mem0_memories"])

    @pytest.mark.asyncio
    async def test_save_learnings_prefers_supermemory(self):
        """save_learnings should save to Supermemory first, skip Mem0 if success."""
        with patch("memory.manager.supermemory_client") as mock_sm, \
             patch("memory.manager.mem0") as mock_mem0, \
             patch("memory.manager.openviking") as mock_ov, \
             patch("memory.manager.graphiti") as mock_graphiti:

            mock_sm.available = True
            mock_sm.add_memory.return_value = "sm-001"
            mock_sm.add_agent_memory.return_value = "sm-002"
            mock_ov.store_resource.return_value = None
            mock_ov.store_agent_memory.return_value = None
            mock_graphiti.add_fact = AsyncMock()

            # Mock redis import
            with patch("memory.manager.set_task_state", new_callable=AsyncMock, create=True):
                from memory.manager import save_learnings
                status = await save_learnings("goal", "result", task_id="t1", user_id="u1")

            assert status["supermemory"] is True
            mock_sm.add_memory.assert_called_once()
            # Mem0 should NOT be called (Supermemory succeeded)
            mock_mem0.add_memory.assert_not_called()


# ─── Data classes ────────────────────────────────────────────────────────────


class TestDataClasses:
    """Test SupermemoryEntry and UserProfile dataclasses."""

    def test_supermemory_entry_defaults(self):
        entry = SupermemoryEntry(id="e1", content="test")
        assert entry.score == 0.0
        assert entry.level == "user"
        assert entry.metadata == {}

    def test_user_profile_defaults(self):
        profile = UserProfile()
        assert profile.static == []
        assert profile.dynamic == []

    def test_user_profile_with_data(self):
        profile = UserProfile(
            static=["Engineer", "Python expert"],
            dynamic=["Working on memory integration"],
        )
        assert len(profile.static) == 2
        assert "Working on memory" in profile.dynamic[0]


# ─── Memory stats ────────────────────────────────────────────────────────────


class TestMemoryStats:
    """Test that get_memory_stats includes Supermemory."""

    def test_stats_include_supermemory(self):
        with patch("memory.manager.supermemory_client") as mock_sm, \
             patch("memory.manager.openviking") as mock_ov, \
             patch("memory.manager.mem0") as mock_mem0, \
             patch("memory.manager.graphiti") as mock_graphiti:

            mock_sm.available = True
            mock_ov.available = True
            mock_ov._fallback_store = {}
            mock_ov.list_paths.return_value = []
            mock_mem0.available = False
            mock_graphiti.get_stats.return_value = {}

            from memory.manager import get_memory_stats
            stats = get_memory_stats()

            assert "supermemory" in stats
            assert stats["supermemory"]["available"] is True
            assert stats["supermemory"]["role"] == "L1 primary (replaces Mem0)"
            assert stats["mem0"]["role"] == "L1 fallback (used when Supermemory unavailable)"
