"""Tests for LiteLLM proxy integration and cost-first model routing."""

import os
from unittest.mock import patch, MagicMock

import httpx
import pytest

from config.model_router import (
    CHEAP,
    CHEAP_QWEN,
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


# ─── Unit tests: cost-first routing ─────────────────────────────────────────

class TestCostFirstRouting:
    """Verify cost-first routing with all API keys configured."""

    @pytest.fixture(autouse=True)
    def mock_all_api_keys(self):
        """Ensure all API keys are present so routing tests hit the primary path."""
        mock = MagicMock()
        mock.qwen_api_key = "qwen-key-test"
        mock.kimi_api_key = "kimi-key-test"
        with patch("config.model_router.settings", mock):
            yield

    def test_orchestrate_always_uses_orchestrator(self):
        for complexity in ("simple", "medium", "complex"):
            result = select_model("orchestrate", complexity)
            assert result.model == ORCHESTRATOR

    def test_code_simple_uses_cheap_qwen(self):
        result = select_model("code", "simple")
        assert result.model == CHEAP_QWEN

    def test_code_medium_uses_workhorse_qwen(self):
        result = select_model("code", "medium")
        assert result.model == WORKHORSE_QWEN

    def test_code_complex_uses_workhorse(self):
        result = select_model("code", "complex")
        assert result.model == WORKHORSE

    def test_research_simple_uses_cheap_qwen(self):
        result = select_model("research", "simple")
        assert result.model == CHEAP_QWEN

    def test_research_medium_uses_workhorse_qwen(self):
        result = select_model("research", "medium")
        assert result.model == WORKHORSE_QWEN

    def test_research_complex_uses_workhorse_with_facts(self):
        result = select_model("research", "complex")
        assert result.model == WORKHORSE
        assert result.supplementary == FACTS

    def test_browser_always_uses_kimi(self):
        for complexity in ("simple", "medium", "complex"):
            result = select_model("browser", complexity)
            assert result.model == WORKHORSE_KIMI

    def test_document_simple_uses_cheap_qwen(self):
        result = select_model("document", "simple")
        assert result.model == CHEAP_QWEN

    def test_document_medium_uses_workhorse_qwen(self):
        result = select_model("document", "medium")
        assert result.model == WORKHORSE_QWEN

    def test_document_complex_uses_gemini(self):
        result = select_model("document", "complex")
        assert result.model == WORKHORSE_GEMINI

    def test_report_simple_uses_cheap_qwen(self):
        result = select_model("report", "simple")
        assert result.model == CHEAP_QWEN

    def test_report_medium_uses_workhorse_qwen(self):
        result = select_model("report", "medium")
        assert result.model == WORKHORSE_QWEN

    def test_report_complex_uses_gemini(self):
        result = select_model("report", "complex")
        assert result.model == WORKHORSE_GEMINI

    def test_route_and_validate_use_cheap_qwen(self):
        for task in ("route", "validate"):
            for complexity in ("simple", "medium", "complex"):
                result = select_model(task, complexity)
                assert result.model == CHEAP_QWEN

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


# ─── Fallback tests: graceful degradation when API keys missing ──────────────

class TestFallbackRouting:
    """Verify fallback when Qwen/Kimi API keys are not configured."""

    def test_qwen_fallback_to_gemini_when_no_key(self):
        with patch("config.model_router.settings") as mock_settings:
            mock_settings.qwen_api_key = ""
            mock_settings.kimi_api_key = "kimi-key-123"
            result = select_model("code", "medium")
            assert result.model == WORKHORSE_GEMINI
            assert "fallback" in result.reason

    def test_cheap_qwen_fallback_to_cheap_when_no_key(self):
        with patch("config.model_router.settings") as mock_settings:
            mock_settings.qwen_api_key = ""
            mock_settings.kimi_api_key = "kimi-key-123"
            result = select_model("code", "simple")
            assert result.model == CHEAP
            assert "fallback" in result.reason

    def test_kimi_fallback_to_workhorse_when_no_key(self):
        with patch("config.model_router.settings") as mock_settings:
            mock_settings.qwen_api_key = "qwen-key-123"
            mock_settings.kimi_api_key = ""
            result = select_model("browser", "medium")
            assert result.model == WORKHORSE
            assert "fallback" in result.reason

    def test_no_fallback_when_keys_present(self):
        with patch("config.model_router.settings") as mock_settings:
            mock_settings.qwen_api_key = "qwen-key-123"
            mock_settings.kimi_api_key = "kimi-key-123"
            result = select_model("code", "simple")
            assert result.model == CHEAP_QWEN
            assert "fallback" not in result.reason

    def test_orchestrator_unaffected_by_missing_keys(self):
        with patch("config.model_router.settings") as mock_settings:
            mock_settings.qwen_api_key = ""
            mock_settings.kimi_api_key = ""
            result = select_model("orchestrate", "complex")
            assert result.model == ORCHESTRATOR

    def test_complex_code_unaffected_by_missing_keys(self):
        with patch("config.model_router.settings") as mock_settings:
            mock_settings.qwen_api_key = ""
            mock_settings.kimi_api_key = ""
            result = select_model("code", "complex")
            assert result.model == WORKHORSE

    def test_supplementary_preserved_in_fallback(self):
        with patch("config.model_router.settings") as mock_settings:
            mock_settings.qwen_api_key = "qwen-key-123"
            mock_settings.kimi_api_key = "kimi-key-123"
            result = select_model("research", "complex")
            assert result.model == WORKHORSE
            assert result.supplementary == FACTS


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
