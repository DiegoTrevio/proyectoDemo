"""Tests for Phase 2: Hermes-first routing and execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hermes_router import select_toolsets_for_goal, should_route_hermes_first


# ─── should_route_hermes_first() tests ──────────────────────────────────


class TestShouldRouteHermesFirst:
    """Tests for the deterministic routing heuristics."""

    @patch("agents.hermes_router.settings")
    def test_disabled_returns_false(self, mock_settings):
        mock_settings.hermes_first_enabled = False
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("write a function") is False

    @patch("agents.hermes_router.settings")
    def test_hermes_disabled_returns_false(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = False
        assert should_route_hermes_first("write a function") is False

    @patch("agents.hermes_router.settings")
    def test_explicit_orchestrator_override(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("write a function", {"routing_mode": "orchestrator"}) is False

    @patch("agents.hermes_router.settings")
    def test_explicit_hermes_first_override(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("any task at all", {"routing_mode": "hermes_first"}) is True

    @patch("agents.hermes_router.settings")
    def test_deep_research_excluded(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("deep research on quantum computing") is False

    @patch("agents.hermes_router.settings")
    def test_comprehensive_analysis_excluded(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("comprehensive analysis of market trends") is False

    @patch("agents.hermes_router.settings")
    def test_multi_source_excluded(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("multi-source research with citations") is False

    @patch("agents.hermes_router.settings")
    def test_slide_deck_excluded(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("create a slide deck about our product") is False

    @patch("agents.hermes_router.settings")
    def test_presentation_excluded(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("build a presentation with 10 slides") is False

    @patch("agents.hermes_router.settings")
    def test_simple_code_included(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("write a function to sort a list") is True

    @patch("agents.hermes_router.settings")
    def test_fix_bug_included(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("fix this bug in the login handler") is True

    @patch("agents.hermes_router.settings")
    def test_simple_research_included(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("search for Python best practices") is True

    @patch("agents.hermes_router.settings")
    def test_how_to_included(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("how to configure nginx for websockets") is True

    @patch("agents.hermes_router.settings")
    def test_file_ops_included(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("read the file config.yaml") is True

    @patch("agents.hermes_router.settings")
    def test_refactor_included(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        assert should_route_hermes_first("refactor the authentication module") is True

    @patch("agents.hermes_router.settings")
    def test_long_goal_excluded(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        long_goal = "a" * 2001
        assert should_route_hermes_first(long_goal) is False

    @patch("agents.hermes_router.settings")
    def test_short_generic_goal_included(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        # Short goal without exclusion patterns → included
        assert should_route_hermes_first("hello world") is True

    @patch("agents.hermes_router.settings")
    def test_auto_routing_mode_uses_heuristics(self, mock_settings):
        mock_settings.hermes_first_enabled = True
        mock_settings.hermes_enabled = True
        # auto mode should fall through to heuristics
        assert should_route_hermes_first("write a script", {"routing_mode": "auto"}) is True


# ─── select_toolsets_for_goal() tests ────────────────────────────────────


class TestSelectToolsetsForGoal:
    """Tests for toolset selection heuristics."""

    def test_code_task(self):
        result = select_toolsets_for_goal("write a function to sort numbers")
        assert result == ["terminal", "file", "code_execution"]

    def test_research_task(self):
        result = select_toolsets_for_goal("search for Python documentation")
        assert result == ["web", "browser"]

    def test_browser_task(self):
        result = select_toolsets_for_goal("navigate to the website and click login")
        assert result == ["browser", "web"]

    def test_file_task(self):
        result = select_toolsets_for_goal("read the file and rename it")
        assert result == ["terminal", "file"]

    def test_generic_task_returns_none(self):
        result = select_toolsets_for_goal("do something interesting")
        assert result is None

    def test_browser_priority_over_code(self):
        # "browse" should win over generic keywords
        result = select_toolsets_for_goal("browse the website and scrape code")
        assert result == ["browser", "web"]


# ─── run_hermes_first() tests ───────────────────────────────────────────


class TestRunHermesFirst:
    """Tests for the Hermes-first execution path."""

    @pytest.mark.asyncio
    @patch("agents.orchestrator._publish", new_callable=AsyncMock)
    @patch("agents.orchestrator.run_task", new_callable=AsyncMock)
    async def test_fallback_on_unavailable(self, mock_run_task, mock_publish):
        mock_run_task.return_value = "orchestrator result"

        with patch("agents.hermes.HermesAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.is_available = AsyncMock(return_value=False)

            from agents.orchestrator import run_hermes_first
            result = await run_hermes_first("t1", "write a script")

        assert result == "orchestrator result"
        mock_run_task.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.orchestrator._publish", new_callable=AsyncMock)
    @patch("agents.orchestrator.run_task", new_callable=AsyncMock)
    async def test_fallback_on_failure(self, mock_run_task, mock_publish):
        mock_run_task.return_value = "orchestrator result"

        with patch("agents.hermes.HermesAgent") as MockAgent:
            from agents.base_agent import AgentResult
            instance = MockAgent.return_value
            instance.is_available = AsyncMock(return_value=True)
            instance.execute = AsyncMock(return_value=AgentResult(
                success=False, output="", error="Hermes failed",
            ))

            from agents.orchestrator import run_hermes_first
            result = await run_hermes_first("t2", "fix a bug")

        assert result == "orchestrator result"
        mock_run_task.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.orchestrator._publish", new_callable=AsyncMock)
    async def test_success_path(self, mock_publish):
        with patch("agents.hermes.HermesAgent") as MockAgent:
            from agents.base_agent import AgentResult
            instance = MockAgent.return_value
            instance.is_available = AsyncMock(return_value=True)
            instance.execute = AsyncMock(return_value=AgentResult(
                success=True, output="Hello World script created!", cost=0.002,
            ))

            with patch("agents.orchestrator.run_task") as mock_run_task:
                from agents.orchestrator import run_hermes_first
                result = await run_hermes_first("t3", "write hello world")

        assert result == "Hello World script created!"
        mock_run_task.assert_not_called()

    @pytest.mark.asyncio
    @patch("agents.orchestrator._publish", new_callable=AsyncMock)
    async def test_publishes_sse_events(self, mock_publish):
        with patch("agents.hermes.HermesAgent") as MockAgent:
            from agents.base_agent import AgentResult
            instance = MockAgent.return_value
            instance.is_available = AsyncMock(return_value=True)
            instance.execute = AsyncMock(return_value=AgentResult(
                success=True, output="Done!", cost=0.001,
            ))

            from agents.orchestrator import run_hermes_first
            await run_hermes_first("t4", "simple task")

        # Verify key SSE events were published
        event_types = [call.args[1] for call in mock_publish.call_args_list]
        assert "thought" in event_types
        assert "action" in event_types
        assert "result" in event_types

    @pytest.mark.asyncio
    @patch("agents.orchestrator._publish", new_callable=AsyncMock)
    @patch("agents.orchestrator.run_task", new_callable=AsyncMock)
    async def test_fallback_on_empty_output(self, mock_run_task, mock_publish):
        mock_run_task.return_value = "orchestrator result"

        with patch("agents.hermes.HermesAgent") as MockAgent:
            from agents.base_agent import AgentResult
            instance = MockAgent.return_value
            instance.is_available = AsyncMock(return_value=True)
            instance.execute = AsyncMock(return_value=AgentResult(
                success=True, output="   ", cost=0.0,
            ))

            from agents.orchestrator import run_hermes_first
            result = await run_hermes_first("t5", "some task")

        assert result == "orchestrator result"
        mock_run_task.assert_called_once()
