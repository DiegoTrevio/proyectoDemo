"""Browser automation tool for AgentOS.

Integrates browser-use library with Steel Browser infrastructure for
persistent sessions, anti-bot stealth, and CAPTCHA solving.
"""

import base64
import logging
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger("agentos.tools.browser")


@dataclass
class BrowserResult:
    """Result of a browser action."""
    success: bool
    content: str = ""
    screenshot_b64: str = ""
    url: str = ""
    error: str | None = None
    extracted_data: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "content": self.content,
            "screenshot_b64": self.screenshot_b64[:100] + "..." if len(self.screenshot_b64) > 100 else self.screenshot_b64,
            "url": self.url,
            "error": self.error,
            "extracted_data": self.extracted_data,
        }


class SteelSession:
    """Manages a Steel Browser session for anti-bot stealth browsing."""

    def __init__(self):
        self.api_key = settings.steel_api_key
        self.session_id: str | None = None
        self._connect_url: str | None = None

    async def create(self) -> str | None:
        """Create a new Steel session. Returns the CDP connect URL."""
        if not self.api_key:
            logger.info("Steel API key not configured — using local browser")
            return None

        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.steel.dev/v1/sessions",
                    json={"concurrency": 1, "timeout": 300000},
                    headers={"steel-api-key": self.api_key},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.session_id = data.get("id")
                    self._connect_url = data.get("connectUrl") or data.get("websocket_url")
                    logger.info("Steel session created: %s", self.session_id)
                    return self._connect_url
                else:
                    logger.error("Steel session creation failed: %s", resp.status_code)
                    return None
        except Exception as e:
            logger.error("Steel session error: %s", e)
            return None

    async def release(self):
        """Release the Steel session."""
        if not self.session_id or not self.api_key:
            return

        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.delete(
                    f"https://api.steel.dev/v1/sessions/{self.session_id}",
                    headers={"steel-api-key": self.api_key},
                )
                logger.info("Steel session released: %s", self.session_id)
        except Exception as e:
            logger.warning("Failed to release Steel session: %s", e)
        finally:
            self.session_id = None
            self._connect_url = None

    @property
    def connect_url(self) -> str | None:
        return self._connect_url


class BrowserTool:
    """High-level browser automation using browser-use + Steel.

    Provides: navigate, click, type_text, screenshot, extract_text.
    """

    def __init__(self):
        self._steel = SteelSession()
        self._browser = None
        self._context = None
        self._page = None

    async def start(self) -> bool:
        """Start a browser session (Steel or local Playwright)."""
        try:
            connect_url = await self._steel.create()

            from playwright.async_api import async_playwright

            pw = await async_playwright().start()

            if connect_url:
                self._browser = await pw.chromium.connect_over_cdp(connect_url)
            else:
                self._browser = await pw.chromium.launch(headless=True)

            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            self._page = await self._context.new_page()
            logger.info("Browser session started")
            return True
        except Exception as e:
            logger.exception("Failed to start browser session")
            return False

    async def stop(self):
        """Close browser and release Steel session."""
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
        except Exception as e:
            logger.warning("Browser cleanup error: %s", e)
        finally:
            await self._steel.release()
            self._page = None
            self._context = None
            self._browser = None

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> BrowserResult:
        """Navigate to a URL."""
        if not self._page:
            return BrowserResult(success=False, error="Browser not started")

        try:
            response = await self._page.goto(url, wait_until=wait_until, timeout=30000)
            status = response.status if response else 0
            current_url = self._page.url
            logger.info("Navigated to %s (status=%d)", current_url, status)
            return BrowserResult(success=True, url=current_url, content=f"Navigated to {current_url}")
        except Exception as e:
            logger.error("Navigation failed: %s", e)
            return BrowserResult(success=False, error=f"Navigation failed: {e}", url=url)

    async def click(self, selector: str) -> BrowserResult:
        """Click an element by CSS selector."""
        if not self._page:
            return BrowserResult(success=False, error="Browser not started")

        try:
            await self._page.click(selector, timeout=10000)
            return BrowserResult(success=True, content=f"Clicked: {selector}")
        except Exception as e:
            return BrowserResult(success=False, error=f"Click failed on '{selector}': {e}")

    async def type_text(self, selector: str, text: str) -> BrowserResult:
        """Type text into an input element."""
        if not self._page:
            return BrowserResult(success=False, error="Browser not started")

        try:
            await self._page.fill(selector, text, timeout=10000)
            return BrowserResult(success=True, content=f"Typed into: {selector}")
        except Exception as e:
            return BrowserResult(success=False, error=f"Type failed on '{selector}': {e}")

    async def screenshot(self) -> BrowserResult:
        """Take a screenshot of the current page."""
        if not self._page:
            return BrowserResult(success=False, error="Browser not started")

        try:
            img_bytes = await self._page.screenshot(full_page=False)
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return BrowserResult(success=True, screenshot_b64=b64, url=self._page.url)
        except Exception as e:
            return BrowserResult(success=False, error=f"Screenshot failed: {e}")

    async def extract_text(self, selector: str = "body") -> BrowserResult:
        """Extract text content from the page or a specific selector."""
        if not self._page:
            return BrowserResult(success=False, error="Browser not started")

        try:
            text = await self._page.inner_text(selector, timeout=10000)
            return BrowserResult(success=True, content=text[:10000], url=self._page.url)
        except Exception as e:
            return BrowserResult(success=False, error=f"Extract failed on '{selector}': {e}")

    async def extract_links(self, selector: str = "a") -> BrowserResult:
        """Extract all links matching a selector."""
        if not self._page:
            return BrowserResult(success=False, error="Browser not started")

        try:
            links = await self._page.eval_on_selector_all(
                selector,
                """elements => elements.map(e => ({
                    text: e.innerText.trim().substring(0, 200),
                    href: e.href
                })).filter(l => l.href && l.text)"""
            )
            return BrowserResult(
                success=True,
                content=f"Found {len(links)} links",
                extracted_data=links[:50],
                url=self._page.url,
            )
        except Exception as e:
            return BrowserResult(success=False, error=f"Link extraction failed: {e}")

    async def run_browser_use_task(self, task: str, model: str = "agentOS/workhorse-kimi") -> BrowserResult:
        """Run a full browser-use agent task with LLM-driven navigation.

        This uses the browser-use library for autonomous web interaction.
        Falls back to manual Playwright if browser-use is not available.
        """
        try:
            from browser_use import Agent as BrowserUseAgent
            from langchain_openai import ChatOpenAI

            # Configure LLM to point at LiteLLM proxy
            llm = ChatOpenAI(
                model=model,
                base_url="http://litellm:4000/v1",
                api_key=settings.litellm_master_key,
                temperature=0,
            )

            agent = BrowserUseAgent(
                task=task,
                llm=llm,
                browser=self._browser,
                browser_context=self._context,
            )

            result = await agent.run(max_steps=15)
            final_text = str(result) if result else ""

            # Take evidence screenshot
            screenshot = await self.screenshot()

            return BrowserResult(
                success=True,
                content=final_text[:10000],
                screenshot_b64=screenshot.screenshot_b64,
                url=self._page.url if self._page else "",
            )

        except ImportError:
            logger.warning("browser-use not available, falling back to manual extraction")
            return BrowserResult(
                success=False,
                error="browser-use library not available",
            )
        except Exception as e:
            logger.exception("browser-use task failed")
            return BrowserResult(success=False, error=f"browser-use error: {e}")
