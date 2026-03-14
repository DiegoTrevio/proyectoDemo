"""Tests for LiteLLM proxy integration and model routing logic."""

import httpx
import pytest

from config.model_router import (
    CHEAP,
    FACTS,
    ORCHESTRATOR,
    WORKHORSE,
    WORKHORSE_GEMINI,
    WORKHORSE_KIMI,
    WORKHORSE_QWEN,
    ModelSelection,
    select_model,
)

LITELLM_BASE_URL = "http://litellm:4000"


# ─── Unit tests: model_router.select_model ────────────────────────────────

class TestSelectModel:
    """Verify routing logic without any external dependencies."""

    def test_orchestrate_always_uses_orchestrator(self):
        for complexity in ("simple", "medium", "complex"):
            result = select_model("orchestrate", complexity)
            assert result.model == ORCHESTRATOR

    def test_research_simple_uses_cheap(self):
        result = select_model("research", "simple")
        assert result.model == CHEAP

    def test_research_medium_uses_gemini(self):
        result = select_model("research", "medium")
        assert result.model == WORKHORSE_GEMINI

    def test_research_complex_uses_workhorse_with_facts(self):
        result = select_model("research", "complex")
        assert result.model == WORKHORSE
        assert result.supplementary == FACTS

    def test_code_simple_uses_qwen(self):
        result = select_model("code", "simple")
        assert result.model == WORKHORSE_QWEN

    def test_code_complex_uses_workhorse(self):
        result = select_model("code", "complex")
        assert result.model == WORKHORSE

    def test_browser_always_uses_kimi(self):
        for complexity in ("simple", "medium", "complex"):
            result = select_model("browser", complexity)
            assert result.model == WORKHORSE_KIMI

    def test_document_simple_uses_qwen(self):
        result = select_model("document", "simple")
        assert result.model == WORKHORSE_QWEN

    def test_document_complex_uses_gemini(self):
        result = select_model("document", "complex")
        assert result.model == WORKHORSE_GEMINI

    def test_route_and_validate_use_cheap(self):
        for task in ("route", "validate"):
            for complexity in ("simple", "medium", "complex"):
                result = select_model(task, complexity)
                assert result.model == CHEAP

    def test_invalid_task_type_raises(self):
        with pytest.raises(ValueError, match="Unknown task_type"):
            select_model("invalid_task", "simple")

    def test_invalid_complexity_raises(self):
        with pytest.raises(ValueError, match="Unknown complexity"):
            select_model("code", "ultra")

    def test_returns_model_selection_dataclass(self):
        result = select_model("code", "simple")
        assert isinstance(result, ModelSelection)
        assert result.reason


# ─── Integration tests: LiteLLM proxy (require running services) ──────────

@pytest.mark.integration
class TestLiteLLMProxy:
    """Integration tests that require a running LiteLLM proxy.

    Run with: pytest -m integration
    """

    @pytest.fixture
    def client(self):
        return httpx.Client(base_url=LITELLM_BASE_URL, timeout=30)

    def test_health_endpoint(self, client: httpx.Client):
        """LiteLLM proxy should respond on /health."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_chat_completion_workhorse(self, client: httpx.Client):
        """Send a simple prompt to agentOS/workhorse and verify response."""
        resp = client.post(
            "/chat/completions",
            json={
                "model": "agentOS/workhorse",
                "messages": [{"role": "user", "content": "Reply with only the word 'hello'."}],
                "max_tokens": 16,
            },
            headers={"Authorization": "Bearer sk-litellm-master"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        content = data["choices"][0]["message"]["content"].lower()
        assert "hello" in content

    def test_model_list_available(self, client: httpx.Client):
        """Verify that models are registered in the proxy."""
        resp = client.get(
            "/model/info",
            headers={"Authorization": "Bearer sk-litellm-master"},
        )
        assert resp.status_code == 200
        data = resp.json()
        model_names = [m.get("model_name", "") for m in data.get("data", [])]
        assert "agentOS/workhorse" in model_names
        assert "agentOS/orchestrator" in model_names
        assert "agentOS/cheap" in model_names
