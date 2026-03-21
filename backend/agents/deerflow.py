"""DeerFlow Agent — delegates complex tasks to DeerFlow 2.0 SuperAgent.

DeerFlow excels at:
  - Deep research (multi-source, cited, comprehensive)
  - Code execution with persistent sandbox (filesystem, bash, Python)
  - Document generation (slides, reports, dashboards, web pages)
  - Multi-step tasks requiring sub-agent coordination

The DeerFlow agent acts as a bridge: it receives tasks from AgentOS's orchestrator
and delegates them to DeerFlow's LangGraph runtime, streaming results back.

Model routing is handled by DeerFlow internally (configured via its own config.yaml).
"""

import logging

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from tools.deerflow_client import DeerFlowClient, get_deerflow_client

logger = logging.getLogger("agentos.agents.deerflow")

# Maps AgentOS task types to DeerFlow skill names
_SKILL_MAP = {
    "research": "research",
    "deep_research": "research",
    "code": None,  # DeerFlow auto-routes code tasks
    "document": "slides",
    "slides": "slides",
    "report": "research",
    "dashboard": None,
    "browser": None,
    "multi": None,  # Let DeerFlow decide
}


class DeerFlowAgent(AbstractAgent):
    """Bridges AgentOS orchestrator to DeerFlow 2.0 SuperAgent runtime.

    For complex tasks, this agent delegates the entire execution to DeerFlow,
    which has its own sandbox, memory, skills, and sub-agent coordination.
    """

    name = "deerflow"
    task_type = "multi"
    default_complexity = "complex"

    def __init__(
        self,
        client: DeerFlowClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        cb_config = CircuitBreakerConfig(
            max_iterations=1,  # DeerFlow handles its own iterations internally
            timeout_seconds=600,  # 10 min max for complex DeerFlow tasks
            max_cost_per_task=10.0,
        )
        super().__init__(circuit_breaker or CircuitBreaker(cb_config))
        self._client = client

    @property
    def client(self) -> DeerFlowClient:
        if self._client is None:
            self._client = get_deerflow_client()
        return self._client

    async def is_available(self) -> bool:
        """Check if DeerFlow service is reachable."""
        try:
            return await self.client.health_check()
        except Exception:
            return False

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Execute a task via DeerFlow 2.0.

        Args:
            task: Dict with {goal, task_id, step_index, task_type?}
            context: Dict with {memory, prior_results}

        Returns:
            AgentResult with DeerFlow's output and artifacts.
        """
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")
        task_type = task.get("task_type", "")

        # Check if DeerFlow is available
        available = await self.is_available()
        if not available:
            logger.warning("DeerFlow not available, cannot execute task")
            return AgentResult(
                success=False,
                output="",
                error="DeerFlow service is not available. Ensure deerflow-langgraph and deerflow-gateway are running.",
            )

        # Build context from prior results
        context_parts = []
        for r in context.get("prior_results", [])[-5:]:
            if r.get("success") and r.get("output"):
                agent = r.get("agent", "unknown")
                context_parts.append(f"[{agent}]: {r['output'][:1500]}")

        # Include memory context
        memory = context.get("memory", {})
        if isinstance(memory, dict) and memory.get("combined"):
            context_parts.insert(0, f"[memory]: {memory['combined'][:1000]}")

        context_str = "\n\n".join(context_parts) if context_parts else ""

        # Use intelligent skill matching
        try:
            from agents.skills.deerflow_skills import match_skill
            skill_match = match_skill(goal, task_type)
            skill = skill_match.skill
            logger.info("DeerFlow skill match: %s (confidence=%.2f, reason=%s)",
                        skill or "auto", skill_match.confidence, skill_match.reason)
        except Exception:
            skill = _SKILL_MAP.get(task_type)

        logger.info(
            "DeerFlow executing: task_id=%s skill=%s goal=%s",
            task_id, skill or "auto", goal[:80],
        )

        # Execute via DeerFlow
        result = await self.client.run_task(
            goal=goal,
            skill=skill,
            context=context_str,
            user_id=task.get("user_id", "default"),
        )

        if result.success:
            logger.info(
                "DeerFlow completed: task_id=%s events=%d artifacts=%d",
                task_id, len(result.events), len(result.artifacts),
            )
        else:
            logger.warning(
                "DeerFlow failed: task_id=%s error=%s",
                task_id, result.error,
            )

        return AgentResult(
            success=result.success,
            output=result.output,
            artifacts=result.artifacts,
            tokens_used=0,  # DeerFlow tracks its own token usage
            cost=0.0,  # Cost tracked by DeerFlow internally
            error=result.error,
        )
