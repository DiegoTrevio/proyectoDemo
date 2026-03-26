"""Browser Agent — navigates websites, extracts data, fills forms.

Uses Kimi K2.5 (agentOS/workhorse-kimi) for massive tool-calling.
Falls back to Claude Sonnet 4.6 for Computer Use API.
Integrates Steel Browser for anti-bot stealth and persistent sessions.
"""

import json
import logging

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from config.model_router import select_model
from tools.browser_tool import BrowserTool

logger = logging.getLogger("agentos.agents.browser")

_MAX_NAVIGATION_STEPS = 10

_SYSTEM_PROMPT = """You are a browser automation expert. You navigate websites, extract data, and interact with web pages.

Rules:
1. Always start by navigating to the target URL
2. Use CSS selectors to find elements
3. Extract only the data requested — be precise
4. Take screenshots as evidence of key steps
5. If a page requires scrolling, extract visible content first
6. Handle popups and cookie banners gracefully"""

_PLAN_PROMPT = """Plan the browser actions needed to accomplish this task.
Respond with JSON only:

{{
  "steps": [
    {{"action": "navigate", "url": "https://..."}},
    {{"action": "extract_text", "selector": "css-selector"}},
    {{"action": "extract_links", "selector": "a.link-class"}},
    {{"action": "click", "selector": "button.load-more"}},
    {{"action": "type", "selector": "input#search", "text": "query"}},
    {{"action": "screenshot"}}
  ],
  "expected_output": "description of what to return"
}}

Available actions: navigate, click, type, extract_text, extract_links, screenshot

Task: {goal}"""

_SYNTHESIZE_PROMPT = """Synthesize the browser extraction results into a clean answer.

Task: {goal}

Extracted data:
{extracted_data}

Respond with a clear, structured answer addressing the task. If the task asks for a list, return a JSON array."""


class BrowserAgent(AbstractAgent):
    """Navigates websites, extracts data, and interacts with web pages."""

    name = "browser"
    task_type = "browser"
    default_complexity = "medium"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None):
        cb_config = CircuitBreakerConfig(
            max_iterations=_MAX_NAVIGATION_STEPS * 2,
            timeout_seconds=180,  # 3 min for browser tasks
        )
        super().__init__(circuit_breaker or CircuitBreaker(cb_config))

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Execute browser task: plan actions, navigate, extract, synthesize."""
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")

        cb_state = self.cb.new_state()
        browser = BrowserTool()
        screenshots = []

        try:
            # ── Step 1: Try browser-use for autonomous navigation ──
            started = await browser.start()
            if not started:
                return AgentResult(
                    success=False, output="",
                    error="Failed to start browser session",
                )

            # First, try the full browser-use agent approach
            browser_model = select_model("browser", "medium").model
            browser_use_result = await browser.run_browser_use_task(
                task=goal, model=browser_model,
            )

            if browser_use_result.success and browser_use_result.content:
                if browser_use_result.screenshot_b64:
                    screenshots.append(browser_use_result.screenshot_b64)

                return AgentResult(
                    success=True,
                    output=browser_use_result.content,
                    artifacts=[
                        {"type": "screenshot", "content_b64": s} for s in screenshots
                    ],
                    tokens_used=cb_state.tokens_used,
                    cost=cb_state.total_cost,
                )

            # ── Step 2: Fallback — LLM-planned manual navigation ──
            logger.info("browser-use unavailable, falling back to planned navigation")

            plan_messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _PLAN_PROMPT.format(goal=goal)},
            ]

            plan_text, cb_state = await self.call_llm(
                plan_messages, cb_state,
                model_override=browser_model,
                max_tokens=2048,
            )

            try:
                plan = self._parse_json(plan_text)
                steps = plan.get("steps", [])
            except (json.JSONDecodeError, ValueError):
                # If LLM can't plan, try simple URL extraction + navigate
                steps = self._fallback_steps(goal)

            # ── Step 3: Execute planned actions ──
            collected_data = []
            for i, step in enumerate(steps[:_MAX_NAVIGATION_STEPS]):
                if cb_state.tripped:
                    break

                action = step.get("action", "")
                logger.info("Browser step %d: %s", i + 1, action)

                if action == "navigate":
                    await self.validate_tool_call(task_id, "browser_navigate", step.get("url", ""))
                    result = await browser.navigate(step.get("url", ""))
                elif action == "click":
                    result = await browser.click(step.get("selector", ""))
                elif action == "type":
                    result = await browser.type_text(
                        step.get("selector", ""), step.get("text", ""),
                    )
                elif action == "extract_text":
                    result = await browser.extract_text(step.get("selector", "body"))
                    if result.success:
                        collected_data.append({
                            "step": i + 1,
                            "action": "extract_text",
                            "content": result.content[:5000],
                        })
                elif action == "extract_links":
                    result = await browser.extract_links(step.get("selector", "a"))
                    if result.success:
                        collected_data.append({
                            "step": i + 1,
                            "action": "extract_links",
                            "links": result.extracted_data,
                        })
                elif action == "screenshot":
                    result = await browser.screenshot()
                    if result.success and result.screenshot_b64:
                        screenshots.append(result.screenshot_b64)
                    continue
                else:
                    logger.warning("Unknown browser action: %s", action)
                    continue

                if not result.success:
                    logger.warning("Step %d failed: %s", i + 1, result.error)

            # ── Step 4: Synthesize results ──
            if collected_data:
                synth_messages = [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _SYNTHESIZE_PROMPT.format(
                        goal=goal,
                        extracted_data=json.dumps(collected_data, indent=2)[:8000],
                    )},
                ]

                output, cb_state = await self.call_llm(
                    synth_messages, cb_state,
                    model_override=browser_model,
                    max_tokens=4096,
                )
            else:
                output = "No data could be extracted from the browser session."

            # Take final screenshot as evidence
            final_screenshot = await browser.screenshot()
            if final_screenshot.success and final_screenshot.screenshot_b64:
                screenshots.append(final_screenshot.screenshot_b64)

            return AgentResult(
                success=bool(collected_data),
                output=output,
                artifacts=[
                    {"type": "screenshot", "content_b64": s} for s in screenshots
                ],
                tokens_used=cb_state.tokens_used,
                cost=cb_state.total_cost,
                error=None if collected_data else "No data extracted",
            )

        except Exception as e:
            logger.exception("Browser agent failed")
            return AgentResult(
                success=False, output="",
                error=f"Browser agent error: {e}",
                tokens_used=cb_state.tokens_used,
                cost=cb_state.total_cost,
            )
        finally:
            await browser.stop()

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        return json.loads(text)

    @staticmethod
    def _fallback_steps(goal: str) -> list[dict]:
        """Extract a URL from the goal and create minimal navigation steps."""
        import re
        urls = re.findall(r"https?://[^\s\"'<>]+", goal)
        steps = []
        if urls:
            steps.append({"action": "navigate", "url": urls[0]})
            steps.append({"action": "extract_text", "selector": "body"})
            steps.append({"action": "extract_links", "selector": "a"})
            steps.append({"action": "screenshot"})
        return steps
