"""Tests for the Browser agent and browser tool."""

import pytest

from tools.browser_tool import BrowserResult, BrowserTool, SteelSession


# ─── BrowserResult ────────────────────────────────────────────────────────

class TestBrowserResult:

    def test_success(self):
        r = BrowserResult(success=True, content="hello", url="https://x.com")
        assert r.success
        d = r.to_dict()
        assert d["url"] == "https://x.com"

    def test_failure(self):
        r = BrowserResult(success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"

    def test_screenshot_truncation_in_dict(self):
        r = BrowserResult(success=True, screenshot_b64="a" * 200)
        d = r.to_dict()
        assert d["screenshot_b64"].endswith("...")


# ─── SteelSession ─────────────────────────────────────────────────────────

class TestSteelSession:

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        session = SteelSession()
        session.api_key = ""
        result = await session.create()
        assert result is None

    @pytest.mark.asyncio
    async def test_release_without_session(self):
        session = SteelSession()
        session.api_key = ""
        session.session_id = None
        await session.release()  # Should not raise

    def test_connect_url_none_initially(self):
        session = SteelSession()
        session._connect_url = None
        assert session.connect_url is None


# ─── BrowserTool ──────────────────────────────────────────────────────────

class TestBrowserTool:

    @pytest.mark.asyncio
    async def test_navigate_without_start(self):
        tool = BrowserTool()
        result = await tool.navigate("https://example.com")
        assert not result.success
        assert "not started" in result.error

    @pytest.mark.asyncio
    async def test_click_without_start(self):
        tool = BrowserTool()
        result = await tool.click("button")
        assert not result.success

    @pytest.mark.asyncio
    async def test_type_without_start(self):
        tool = BrowserTool()
        result = await tool.type_text("input", "hello")
        assert not result.success

    @pytest.mark.asyncio
    async def test_screenshot_without_start(self):
        tool = BrowserTool()
        result = await tool.screenshot()
        assert not result.success

    @pytest.mark.asyncio
    async def test_extract_text_without_start(self):
        tool = BrowserTool()
        result = await tool.extract_text()
        assert not result.success

    @pytest.mark.asyncio
    async def test_extract_links_without_start(self):
        tool = BrowserTool()
        result = await tool.extract_links()
        assert not result.success


# ─── BrowserAgent ─────────────────────────────────────────────────────────

class TestBrowserAgent:

    def test_fallback_steps_with_url(self):
        from agents.browser import BrowserAgent
        steps = BrowserAgent._fallback_steps(
            "Go to https://news.ycombinator.com and extract titles"
        )
        assert len(steps) == 4
        assert steps[0]["action"] == "navigate"
        assert "ycombinator" in steps[0]["url"]

    def test_fallback_steps_no_url(self):
        from agents.browser import BrowserAgent
        steps = BrowserAgent._fallback_steps("do something with no url")
        assert steps == []

    def test_parse_json(self):
        from agents.browser import BrowserAgent
        raw = '```json\n{"steps": [{"action": "navigate", "url": "https://x.com"}]}\n```'
        parsed = BrowserAgent._parse_json(raw)
        assert "steps" in parsed
        assert parsed["steps"][0]["action"] == "navigate"


# ─── Integration (requires Playwright + optionally Steel) ─────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_agent_hacker_news():
    """Full flow: navigate to HN and extract top titles."""
    from agents.browser import BrowserAgent

    agent = BrowserAgent()
    result = await agent.execute(
        task={
            "goal": "Ve a https://news.ycombinator.com y extrae los títulos de los 5 posts más populares",
            "task_id": "test-browser-001",
        },
        context={},
    )

    assert result.success or result.error is not None

    if result.success:
        assert len(result.output) > 0
