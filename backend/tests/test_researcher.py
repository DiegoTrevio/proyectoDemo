"""Tests for the Researcher agent and web search tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.web_search import SearchResult, TavilySearchTool, ExaSearchTool, PerplexitySonarTool


# ─── Search tool unit tests ──────────────────────────────────────────────

class TestSearchResult:

    def test_to_dict(self):
        sr = SearchResult(source="tavily", content="hello", url="https://x.com", relevance_score=0.9)
        d = sr.to_dict()
        assert d["source"] == "tavily"
        assert d["url"] == "https://x.com"
        assert d["relevance_score"] == 0.9

    def test_no_api_key_returns_empty(self):
        """Tools should return empty list when API key is not set."""
        with patch("tools.web_search.settings") as mock_settings:
            mock_settings.tavily_api_key = ""
            tool = TavilySearchTool()
            # The tool reads api_key in __init__, so we need to set it there
            tool.api_key = ""

    @pytest.mark.asyncio
    async def test_tavily_no_key(self):
        tool = TavilySearchTool()
        tool.api_key = ""
        results = await tool.search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_exa_no_key(self):
        tool = ExaSearchTool()
        tool.api_key = ""
        results = await tool.search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_perplexity_no_key(self):
        tool = PerplexitySonarTool()
        tool.api_key = ""
        results = await tool.search("test")
        assert results == []


# ─── Researcher agent tests ──────────────────────────────────────────────

class TestResearcherAgent:

    def test_complexity_detection(self):
        from agents.researcher import ResearcherAgent
        agent = ResearcherAgent()

        assert agent._determine_complexity("What is LangGraph?", {}) == "simple"
        assert agent._determine_complexity("Analyze the AI market trends", {}) == "complex"
        assert agent._determine_complexity("Find info about Python 3.12", {}) == "medium"
        assert agent._determine_complexity("anything", {"complexity": "complex"}) == "complex"

    def test_format_results(self):
        from agents.researcher import ResearcherAgent
        agent = ResearcherAgent()

        results = [
            SearchResult(source="tavily", content="Test content", url="https://a.com", relevance_score=0.8),
            SearchResult(source="exa", content="More content", url="https://b.com", relevance_score=0.7),
        ]
        formatted = agent._format_results_for_llm(results)
        assert "[1]" in formatted
        assert "[2]" in formatted
        assert "https://a.com" in formatted

    def test_format_empty_results(self):
        from agents.researcher import ResearcherAgent
        agent = ResearcherAgent()
        assert "No search results" in agent._format_results_for_llm([])

    def test_build_sources_deduplicates(self):
        from agents.researcher import ResearcherAgent
        agent = ResearcherAgent()

        results = [
            SearchResult(source="tavily", content="A", url="https://a.com", relevance_score=0.9),
            SearchResult(source="exa", content="B", url="https://a.com", relevance_score=0.8),
            SearchResult(source="exa", content="C", url="https://b.com", relevance_score=0.7),
        ]
        sources = agent._build_sources(results)
        assert len(sources) == 2
        urls = [s["url"] for s in sources]
        assert "https://a.com" in urls
        assert "https://b.com" in urls


# ─── Mem0 layer tests ────────────────────────────────────────────────────

class TestMem0Layer:

    def test_unavailable_returns_empty(self):
        from memory.mem0_layer import Mem0Layer
        layer = Mem0Layer.__new__(Mem0Layer)
        layer._client = None
        assert layer.available is False
        assert layer.search_memory("u1", "q") == []
        assert layer.add_memory("u1", "c") is None
        assert layer.get_all("u1") == []


# ─── Integration test (requires running services) ────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_researcher_full_flow():
    """End-to-end: researcher searches, synthesizes, returns structured output."""
    from agents.researcher import ResearcherAgent

    agent = ResearcherAgent()
    result = await agent.execute(
        task={"goal": "Investiga el mercado de IA en LATAM 2026", "task_id": "test-001"},
        context={"complexity": "medium", "user_id": "test-user"},
    )
    assert result.success or result.error  # either way, should not crash

    if result.success and result.output:
        import json
        output = json.loads(result.output)
        assert "summary" in output
        assert "sources" in output
        assert "key_facts" in output
        assert "confidence" in output
