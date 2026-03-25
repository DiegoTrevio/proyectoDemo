"""Tests for Hermes Agent integration — client (HTTP + CLI), Paperclip bridge, and dispatcher."""

import os

os.environ["TESTING"] = "1"

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.hermes_client import HermesClient, HermesResult, _SESSION_ID_RE, _INPUT_TOKENS_RE


# ─── HermesClient output parsing (CLI mode) ──────────────────────────────────


class TestHermesOutputParsing:
    """Test regex patterns and _parse_output logic."""

    def _client(self) -> HermesClient:
        return HermesClient(cli_path="hermes", model="test/model", timeout=60)

    def test_parse_session_id(self):
        assert _SESSION_ID_RE.search("session_id: abc-123").group(1) == "abc-123"
        assert _SESSION_ID_RE.search("session_id: my_session_42").group(1) == "my_session_42"
        assert _SESSION_ID_RE.search("no session here") is None

    def test_parse_token_counts(self):
        assert _INPUT_TOKENS_RE.search("input_tokens: 1,234").group(1) == "1,234"
        assert _INPUT_TOKENS_RE.search("Input Tokens: 500").group(1) == "500"

    def test_parse_successful_output(self):
        client = self._client()
        stdout = "Hello world\nsession_id: sess-001\ninput_tokens: 100\noutput_tokens: 50\n"
        stderr = "INFO: started\n$0.0035\n"
        result = client._parse_output(stdout, stderr, exit_code=0, timed_out=False)

        assert result.success is True
        assert "Hello world" in result.output
        assert result.session_id == "sess-001"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cost == 0.0035
        assert result.errors == []
        assert result.mode == "cli"

    def test_parse_failed_output(self):
        client = self._client()
        result = client._parse_output("", "Error: something broke\n", exit_code=1, timed_out=False)

        assert result.success is False
        assert result.exit_code == 1
        assert any("something broke" in e for e in result.errors)

    def test_parse_timeout(self):
        client = self._client()
        result = client._parse_output("partial output", "", exit_code=None, timed_out=True)

        assert result.success is False
        assert result.timed_out is True
        assert any("timed out" in e for e in result.errors)

    def test_filters_info_noise_from_stderr(self):
        client = self._client()
        stderr = "INFO: loading model\nDEBUG: cache hit\nError: real problem\nwarning: minor\n"
        result = client._parse_output("output", stderr, exit_code=1, timed_out=False)

        # Only real errors, not INFO/DEBUG/warn
        assert len(result.errors) == 1
        assert "real problem" in result.errors[0]

    def test_strips_tool_and_thinking_markers(self):
        client = self._client()
        stdout = "line 1\n┊tool output here\n💭 thinking...\nline 2\n"
        result = client._parse_output(stdout, "", exit_code=0, timed_out=False)

        assert "tool output" not in result.output
        assert "thinking" not in result.output
        assert "line 1" in result.output
        assert "line 2" in result.output

    def test_caps_errors_at_five(self):
        client = self._client()
        stderr = "\n".join(f"Error: problem {i}" for i in range(10))
        result = client._parse_output("", stderr, exit_code=1, timed_out=False)
        assert len(result.errors) == 5


# ─── HermesClient HTTP API mode ─────────────────────────────────────────────


class TestHermesHTTPMode:
    """Test HTTP API mode (v0.4.0+)."""

    def test_use_http_when_api_url_set(self):
        client = HermesClient(cli_path="hermes", model="test/model", timeout=60, api_url="http://hermes:3000")
        assert client._use_http is True

    def test_use_cli_when_no_api_url(self):
        client = HermesClient(cli_path="hermes", model="test/model", timeout=60, api_url="")
        assert client._use_http is False

    def test_parse_http_response(self):
        client = HermesClient(cli_path="hermes", model="test/model", timeout=60, api_url="http://hermes:3000")
        data = {
            "id": "chatcmpl-abc123",
            "choices": [{"message": {"role": "assistant", "content": "Hello from Hermes!"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cost": 0.005,
            },
            "session_id": "sess-http-001",
        }
        result = client._parse_http_response(data)

        assert result.success is True
        assert result.output == "Hello from Hermes!"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cost == 0.005
        assert result.session_id == "sess-http-001"
        assert result.mode == "http"

    def test_parse_http_response_minimal(self):
        client = HermesClient(cli_path="hermes", model="test/model", timeout=60, api_url="http://hermes:3000")
        data = {
            "id": "chatcmpl-xyz",
            "choices": [{"message": {"content": "Done"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        result = client._parse_http_response(data)

        assert result.success is True
        assert result.output == "Done"
        assert result.cost == 0.0
        assert result.session_id == "chatcmpl-xyz"  # Falls back to response id


# ─── HermesClient CLI interaction ────────────────────────────────────────────


class TestHermesClientCLI:
    """Test CLI argument building and subprocess management."""

    def test_build_args_basic(self):
        client = HermesClient(cli_path="hermes", model="anthropic/claude-sonnet-4", timeout=300)
        args = client._build_args("Do something")

        assert args[0] == "hermes"
        assert "chat" in args
        assert "-q" in args
        assert "Do something" in args
        assert "-Q" in args
        assert "-m" in args
        assert "anthropic/claude-sonnet-4" in args

    def test_build_args_with_session_resume(self):
        client = HermesClient(cli_path="hermes", model="test/model", timeout=60, persist_session=True)
        args = client._build_args("task", session_id="sess-001")
        assert "--resume" in args
        assert "sess-001" in args

    def test_build_args_no_resume_when_disabled(self):
        client = HermesClient(cli_path="hermes", model="test/model", timeout=60, persist_session=False)
        args = client._build_args("task", session_id="sess-001")
        assert "--resume" not in args

    def test_build_args_with_toolsets(self):
        client = HermesClient(
            cli_path="hermes", model="test/model", timeout=60,
            enabled_toolsets=["terminal", "web"],
        )
        args = client._build_args("task")
        assert args.count("--tools") == 2
        assert "terminal" in args
        assert "web" in args

    @pytest.mark.asyncio
    async def test_is_available_returns_false_when_not_installed(self):
        client = HermesClient(cli_path="nonexistent-hermes-binary", model="test/model", timeout=10)
        assert await client.is_available() is False

    @pytest.mark.asyncio
    async def test_run_returns_error_when_cli_not_found(self):
        client = HermesClient(cli_path="nonexistent-hermes-binary", model="test/model", timeout=10)
        result = await client.run("test prompt")
        assert result.success is False
        assert any("not found" in e.lower() for e in result.errors)


# ─── HermesAgent ─────────────────────────────────────────────────────────────


class TestHermesAgent:
    """Test HermesAgent execute logic."""

    @pytest.mark.asyncio
    async def test_execute_when_unavailable(self):
        from agents.hermes import HermesAgent

        mock_client = MagicMock()
        mock_client.is_available = AsyncMock(return_value=False)

        agent = HermesAgent(client=mock_client)
        result = await agent.execute({"goal": "test task"}, {})

        assert result.success is False
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self):
        from agents.hermes import HermesAgent

        mock_client = MagicMock()
        mock_client.is_available = AsyncMock(return_value=True)
        mock_client._use_http = False
        mock_client.run = AsyncMock(return_value=HermesResult(
            success=True,
            output="Task completed successfully",
            session_id="sess-001",
            input_tokens=100,
            output_tokens=50,
            cost=0.005,
        ))

        agent = HermesAgent(client=mock_client)
        result = await agent.execute(
            {"goal": "Research topic", "task_id": "t-001", "task_type": "research"},
            {"prior_results": [], "memory": {}},
        )

        assert result.success is True
        assert "Task completed" in result.output
        assert result.tokens_used == 150
        assert result.cost == 0.005
        mock_client.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_context(self):
        from agents.hermes import HermesAgent

        mock_client = MagicMock()
        mock_client.is_available = AsyncMock(return_value=True)
        mock_client._use_http = False
        mock_client.run = AsyncMock(return_value=HermesResult(
            success=True, output="Done",
        ))

        agent = HermesAgent(client=mock_client)
        await agent.execute(
            {"goal": "Next step", "task_id": "t-002"},
            {
                "prior_results": [
                    {"success": True, "output": "Previous result", "agent": "researcher"},
                ],
                "memory": {"combined": "Remember this context"},
            },
        )

        call_kwargs = mock_client.run.call_args
        assert "Remember this context" in call_kwargs.kwargs.get("context", "")


# ─── Paperclip adapter bridge ───────────────────────────────────────────────


class TestPaperclipBridge:
    """Test Paperclip adapter template rendering and task assignment."""

    def test_render_template_simple(self):
        from tools.hermes_paperclip import render_template
        template = "Hello {{agentName}}, work on {{taskTitle}}"
        result = render_template(template, {"agentName": "Hermes", "taskTitle": "Research AI"})
        assert result == "Hello Hermes, work on Research AI"

    def test_render_template_conditional_present(self):
        from tools.hermes_paperclip import render_template
        template = "{{#taskId}}Task: {{taskId}}{{/taskId}}{{#noTask}}No task assigned{{/noTask}}"
        result = render_template(template, {"taskId": "t-001"})
        assert "Task: t-001" in result
        assert "No task assigned" not in result

    def test_render_template_conditional_absent(self):
        from tools.hermes_paperclip import render_template
        template = "{{#taskId}}Task: {{taskId}}{{/taskId}}{{#noTask}}No task assigned{{/noTask}}"
        result = render_template(template, {})
        assert "No task assigned" in result
        assert "Task:" not in result

    @pytest.mark.asyncio
    async def test_assign_task(self):
        from tools.hermes_paperclip import PaperclipBridge

        mock_client = MagicMock()
        mock_client.run = AsyncMock(return_value=HermesResult(
            success=True, output="Task completed via Paperclip",
        ))

        bridge = PaperclipBridge(client=mock_client)
        result = await bridge.assign_task(
            task_id="t-001",
            title="Research AI safety",
            body="Find latest papers on AI alignment.",
        )

        assert result.success is True
        mock_client.run.assert_called_once()
        call_kwargs = mock_client.run.call_args
        assert "Research AI safety" in call_kwargs.kwargs.get("prompt", call_kwargs.args[0] if call_kwargs.args else "")


# ─── Dispatcher registration ────────────────────────────────────────────────


class TestDispatcherRegistration:
    """Test that Hermes integrates with the agent dispatcher."""

    def test_hermes_not_registered_when_disabled(self):
        with patch.dict(os.environ, {"HERMES_ENABLED": "false"}):
            # Force re-import to pick up new settings
            from agents.dispatcher import get_available_agents
            agents = get_available_agents()
            # Hermes should not be in registry when disabled (default)
            assert "hermes" not in agents

    def test_hermes_agent_has_correct_attributes(self):
        from agents.hermes import HermesAgent
        agent = HermesAgent(client=MagicMock())
        assert agent.name == "hermes"
        assert agent.task_type == "multi"
        assert agent.default_complexity == "complex"
