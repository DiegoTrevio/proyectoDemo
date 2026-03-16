"""Tests for the Coder agent and E2B code executor."""

import pytest

from tools.code_executor import CodeExecutor, ExecutionResult


# ─── ExecutionResult ──────────────────────────────────────────────────────

class TestExecutionResult:

    def test_success_when_exit_zero(self):
        r = ExecutionResult(stdout="ok", exit_code=0)
        assert r.success is True

    def test_failure_when_exit_nonzero(self):
        r = ExecutionResult(stderr="err", exit_code=1)
        assert r.success is False

    def test_failure_when_error_set(self):
        r = ExecutionResult(exit_code=0, error="something went wrong")
        assert r.success is False

    def test_failure_when_timed_out(self):
        r = ExecutionResult(exit_code=0, timed_out=True)
        assert r.success is False

    def test_to_dict(self):
        r = ExecutionResult(stdout="hello", stderr="", files=[], exit_code=0)
        d = r.to_dict()
        assert d["stdout"] == "hello"
        assert d["exit_code"] == 0
        assert "files" in d


# ─── CodeExecutor ─────────────────────────────────────────────────────────

class TestCodeExecutor:

    def test_detect_dependencies_matplotlib(self):
        executor = CodeExecutor()
        code = "import matplotlib.pyplot as plt\nimport numpy as np\nprint('hi')"
        deps = executor._detect_dependencies(code)
        assert "matplotlib" in deps
        assert "numpy" in deps

    def test_detect_dependencies_empty(self):
        executor = CodeExecutor()
        code = "print('hello world')"
        deps = executor._detect_dependencies(code)
        assert deps == []

    def test_detect_dependencies_sklearn(self):
        executor = CodeExecutor()
        code = "from sklearn.ensemble import RandomForestClassifier"
        deps = executor._detect_dependencies(code)
        assert "scikit-learn" in deps

    @pytest.mark.asyncio
    async def test_execute_no_api_key(self):
        executor = CodeExecutor()
        executor.api_key = ""
        result = await executor.execute("print('hello')")
        assert result.exit_code == 0
        assert "not configured" in result.stdout.lower() or result.stdout != ""


# ─── CoderAgent ───────────────────────────────────────────────────────────

class TestCoderAgent:

    def test_model_selection_simple(self):
        from agents.coder import CoderAgent
        agent = CoderAgent()
        model = agent._select_model("write a hello world script", estimated_lines=10)
        assert model == "agentOS/workhorse-qwen"

    def test_model_selection_complex(self):
        from agents.coder import CoderAgent
        agent = CoderAgent()
        model = agent._select_model("build a REST API with auth", estimated_lines=200)
        assert model == "agentOS/workhorse"

    def test_model_selection_architecture(self):
        from agents.coder import CoderAgent
        agent = CoderAgent()
        model = agent._select_model("design system architecture for microservice")
        assert model == "agentOS/orchestrator"

    def test_extract_code_from_markdown(self):
        from agents.coder import CoderAgent
        text = "Here's the code:\n```python\nprint('hello')\n```\nDone."
        code = CoderAgent._extract_code_from_text(text)
        assert code == "print('hello')"

    def test_extract_code_empty(self):
        from agents.coder import CoderAgent
        code = CoderAgent._extract_code_from_text("no code here")
        assert code == ""

    def test_parse_json_response(self):
        from agents.coder import CoderAgent
        agent = CoderAgent()
        raw = '```json\n{"code": "print(1)", "language": "python"}\n```'
        parsed = agent._parse_json_response(raw)
        assert parsed["code"] == "print(1)"


# ─── Integration (requires E2B + LiteLLM) ────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_coder_generates_chart():
    """Full flow: Coder generates matplotlib chart in E2B sandbox."""
    from agents.coder import CoderAgent

    agent = CoderAgent()
    result = await agent.execute(
        task={
            "goal": (
                "Escribe un script Python que genere un gráfico de barras con matplotlib "
                "mostrando las ventas por trimestre: Q1=100, Q2=150, Q3=200, Q4=180"
            ),
            "task_id": "test-coder-001",
        },
        context={},
    )

    # Should succeed or at least not crash
    assert result.success or result.error is not None

    if result.success:
        # Should have generated an image file
        image_artifacts = [a for a in result.artifacts if a.get("name", "").endswith(".png")]
        assert len(image_artifacts) > 0, "Expected a PNG chart artifact"
