"""Agent dispatcher — routes sub-tasks to the correct agent implementation."""

import logging

from agents.base_agent import AgentResult

logger = logging.getLogger("agentos.dispatcher")


# ─── Stub agents (to be replaced with real implementations) ───────────────

class _StubAgent:
    """Placeholder agent that returns a not-implemented message."""

    def __init__(self, name: str):
        self.name = name

    async def execute(self, task: dict, context: dict) -> AgentResult:
        goal = task.get("goal", task.get("description", ""))
        return AgentResult(
            success=True,
            output=f"[{self.name}] Stub result for: {goal}",
            tokens_used=0,
            cost=0.0,
        )


def _build_registry() -> dict:
    """Build agent registry with real implementations where available."""
    registry: dict = {
        "document_writer": _StubAgent("document_writer"),
        "validator": _StubAgent("validator"),
    }

    # Register real Researcher agent
    try:
        from agents.researcher import ResearcherAgent
        registry["researcher"] = ResearcherAgent()
    except Exception as e:
        logger.warning("Failed to load ResearcherAgent, using stub: %s", e)
        registry["researcher"] = _StubAgent("researcher")

    # Register real Coder agent
    try:
        from agents.coder import CoderAgent
        registry["coder"] = CoderAgent()
    except Exception as e:
        logger.warning("Failed to load CoderAgent, using stub: %s", e)
        registry["coder"] = _StubAgent("coder")

    # Register real Browser agent
    try:
        from agents.browser import BrowserAgent
        registry["browser"] = BrowserAgent()
    except Exception as e:
        logger.warning("Failed to load BrowserAgent, using stub: %s", e)
        registry["browser"] = _StubAgent("browser")

    return registry


# Agent registry — maps agent names to their implementations
_AGENT_REGISTRY = _build_registry()


def get_available_agents() -> list[str]:
    """Return list of registered agent names."""
    return list(_AGENT_REGISTRY.keys())


async def dispatch(agent_name: str, task: dict, context: dict) -> AgentResult:
    """Dispatch a sub-task to the named agent.

    Args:
        agent_name: Name of the agent to dispatch to (e.g. "researcher", "coder").
        task: Dict with at least {goal, step_index} describing the sub-task.
        context: Shared context dict (memory, prior results, etc.).

    Returns:
        AgentResult from the dispatched agent.
    """
    agent = _AGENT_REGISTRY.get(agent_name)
    if not agent:
        logger.warning("Unknown agent '%s', falling back to researcher", agent_name)
        agent = _AGENT_REGISTRY["researcher"]

    logger.info("Dispatching to agent=%s task=%s", agent_name, task.get("goal", "")[:80])
    return await agent.execute(task, context)
