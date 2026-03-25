"""Agent dispatcher — routes sub-tasks to the correct agent implementation."""

import logging

from agents.base_agent import AgentResult

logger = logging.getLogger("agentos.dispatcher")


# ─── Stub agents (to be replaced with real implementations) ───────────────

class _StubAgent:
    """Placeholder agent used when a real agent fails to load."""

    def __init__(self, name: str):
        self.name = name

    async def execute(self, task: dict, context: dict) -> AgentResult:
        goal = task.get("goal", task.get("description", ""))
        return AgentResult(
            success=False,
            output=(
                f"[UNAVAILABLE] Agent '{self.name}' could not be loaded. "
                f"Check dependencies or configuration. Task was: {goal}"
            ),
            tokens_used=0,
            cost=0.0,
            is_stub=True,
        )


def _build_registry() -> dict:
    """Build agent registry with real implementations where available."""
    registry: dict = {}

    # Register real Validator agent
    try:
        from agents.validator import ValidatorAgent
        registry["validator"] = ValidatorAgent()
    except Exception as e:
        logger.warning("Failed to load ValidatorAgent, using stub: %s", e)
        registry["validator"] = _StubAgent("validator")

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

    # Register real Document agent
    try:
        from agents.document import DocumentAgent
        registry["document_writer"] = DocumentAgent()
    except Exception as e:
        logger.warning("Failed to load DocumentAgent, using stub: %s", e)
        registry["document_writer"] = _StubAgent("document_writer")

    # Register DeerFlow agent (for complex/deep tasks)
    try:
        from config.settings import settings
        if settings.deerflow_enabled:
            from agents.deerflow import DeerFlowAgent
            registry["deerflow"] = DeerFlowAgent()
            logger.info("DeerFlow agent registered")
        else:
            logger.info("DeerFlow disabled in settings — skipping registration")
    except Exception as e:
        logger.warning("Failed to load DeerFlowAgent: %s", e)

    # Register Hermes agent (Nous Research — multi-tool CLI agent)
    try:
        from config.settings import settings
        if settings.hermes_enabled:
            from agents.hermes import HermesAgent
            registry["hermes"] = HermesAgent()
            logger.info("Hermes agent registered")
        else:
            logger.info("Hermes disabled in settings — skipping registration")
    except Exception as e:
        logger.warning("Failed to load HermesAgent: %s", e)

    return registry


# Agent registry — maps agent names to their implementations
_AGENT_REGISTRY = _build_registry()


def get_available_agents() -> list[str]:
    """Return list of registered agent names."""
    return list(_AGENT_REGISTRY.keys())


def get_agent_status() -> dict:
    """Return status of each registered agent (real vs stub)."""
    return {
        name: {
            "available": not isinstance(agent, _StubAgent),
            "type": type(agent).__name__,
        }
        for name, agent in _AGENT_REGISTRY.items()
    }


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

    if isinstance(agent, _StubAgent):
        logger.warning("STUB agent used for '%s' — real agent unavailable", agent_name)

    logger.info("Dispatching to agent=%s task=%s", agent_name, task.get("goal", "")[:80])
    return await agent.execute(task, context)
