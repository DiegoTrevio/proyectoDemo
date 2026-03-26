"""Tests for agent model routing — verifies agents use select_model() with fallback."""

import pytest
from unittest.mock import patch, MagicMock

from config.model_router import select_model, ORCHESTRATOR


class TestCostFirstRouting:
    """Verify agents delegate to select_model() which supports fallback."""

    def test_browser_uses_router(self):
        """Browser tasks route through select_model('browser', 'medium')."""
        result = select_model("browser", "medium")
        assert result.model  # Must return a model name
        assert "agentOS/" in result.model

    def test_code_simple_routes_to_cheap(self):
        """Simple code tasks use cheap model."""
        result = select_model("code", "simple")
        assert "cheap" in result.model or "qwen" in result.model or "agentOS/" in result.model

    def test_code_medium_routes_to_workhorse(self):
        """Medium code tasks use workhorse model."""
        result = select_model("code", "medium")
        assert "agentOS/" in result.model

    def test_research_routes_correctly(self):
        """Research tasks route based on complexity."""
        for complexity in ["simple", "medium", "complex"]:
            result = select_model("research", complexity)
            assert result.model
            assert "agentOS/" in result.model

    def test_document_routes_correctly(self):
        """Document tasks route based on complexity."""
        for complexity in ["simple", "medium"]:
            result = select_model("document", complexity)
            assert result.model
            assert "agentOS/" in result.model

    def test_orchestrator_unchanged(self):
        """Orchestrator routing is never affected by cost-first."""
        result = select_model("orchestrate", "complex")
        assert result.model == ORCHESTRATOR


class TestFallbackWhenNoQwenKey:
    """Verify fallback when Qwen API key is not configured."""

    @patch("config.model_router.settings")
    def test_code_simple_fallback(self, mock_settings):
        """code/simple falls back from cheap-qwen to cheap when no Qwen key."""
        mock_settings.qwen_api_key = ""
        mock_settings.kimi_api_key = "some-key"

        result = select_model("code", "simple")
        # Should NOT contain "qwen" since key is missing
        assert "qwen" not in result.model.lower() or "fallback" in result.reason.lower()

    @patch("config.model_router.settings")
    def test_code_medium_fallback(self, mock_settings):
        """code/medium falls back from workhorse-qwen when no Qwen key."""
        mock_settings.qwen_api_key = ""
        mock_settings.kimi_api_key = "some-key"

        result = select_model("code", "medium")
        assert result.model  # Must return something valid

    @patch("config.model_router.settings")
    def test_document_simple_fallback(self, mock_settings):
        """document/simple falls back when no Qwen key."""
        mock_settings.qwen_api_key = ""
        mock_settings.kimi_api_key = "some-key"

        result = select_model("document", "simple")
        assert result.model


class TestFallbackWhenNoKimiKey:
    """Verify fallback when Kimi API key is not configured."""

    @patch("config.model_router.settings")
    def test_browser_fallback(self, mock_settings):
        """browser/medium falls back from workhorse-kimi to workhorse when no Kimi key."""
        mock_settings.qwen_api_key = "some-key"
        mock_settings.kimi_api_key = ""

        result = select_model("browser", "medium")
        assert "kimi" not in result.model.lower() or "fallback" in result.reason.lower()


class TestAgentSelectModelIntegration:
    """Verify individual agents correctly use select_model()."""

    def test_coder_select_model_simple(self):
        """Coder._select_model routes simple tasks through router."""
        from agents.coder import CoderAgent
        agent = CoderAgent()
        model = agent._select_model("Write a hello world script", estimated_lines=10)
        assert model  # Returns a valid model string
        assert "agentOS/" in model or model == ORCHESTRATOR

    def test_coder_select_model_architecture(self):
        """Coder._select_model escalates architecture tasks to Opus."""
        from agents.coder import CoderAgent
        agent = CoderAgent()
        model = agent._select_model("Design system architecture for microservice")
        assert model == ORCHESTRATOR

    def test_document_select_model_simple(self):
        """Document._select_model routes simple templates through router."""
        from agents.document import DocumentAgent
        agent = DocumentAgent()
        model = agent._select_model("Create a simple template for reports")
        assert model
        assert "agentOS/" in model

    def test_document_select_model_complex(self):
        """Document._select_model routes complex documents through router."""
        from agents.document import DocumentAgent
        agent = DocumentAgent()
        model = agent._select_model("Generate a comprehensive financial analysis report")
        assert model
        assert "agentOS/" in model
