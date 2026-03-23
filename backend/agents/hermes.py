"""Hermes Agent — delegates tasks to Nous Research's Hermes Agent CLI.

Hermes excels at:
  - Complex multi-tool tasks (30+ native tools: terminal, files, web, git, browser, vision)
  - Tasks requiring persistent memory across sessions
  - Specialized skills (80+ loadable skills)
  - Multi-step autonomous execution with session resumption

The Hermes agent acts as a bridge: it receives tasks from AgentOS's orchestrator
and delegates them to the Hermes CLI in single-query mode, parsing structured output.

Ported from: github.com/NousResearch/hermes-paperclip-adapter
"""

import logging

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from tools.hermes_client import HermesClient, get_hermes_client

logger = logging.getLogger("agentos.agents.hermes")

# Maps AgentOS task types to Hermes toolsets
_TOOLSET_MAP = {
    "code": ["terminal", "file", "code_execution"],
    "research": ["web", "browser"],
    "browser": ["browser", "web"],
    "document": ["file", "creative", "productivity"],
    "multi": None,  # Let Hermes use all available tools
}


class HermesAgent(AbstractAgent):
    """Bridges AgentOS orchestrator to Hermes Agent CLI.

    For tasks that benefit from Hermes's native tool suite (terminal, git,
    browser, vision, etc.), this agent spawns Hermes as a subprocess and
    captures its output.
    """

    name = "hermes"
    task_type = "multi"
    default_complexity = "complex"

    def __init__(
        self,
        client: HermesClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        cb_config = CircuitBreakerConfig(
            max_iterations=1,  # Hermes handles its own iterations internally
            timeout_seconds=600,  # 10 min max
            max_cost_per_task=5.0,
        )
        super().__init__(circuit_breaker or CircuitBreaker(cb_config))
        self._client = client

    @property
    def client(self) -> HermesClient:
        if self._client is None:
            self._client = get_hermes_client()
        return self._client

    async def is_available(self) -> bool:
        """Check if the Hermes CLI is installed and accessible."""
        try:
            return await self.client.is_available()
        except Exception:
            return False

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Execute a task via Hermes Agent CLI.

        Args:
            task: Dict with {goal, task_id, step_index, task_type?}
            context: Dict with {memory, prior_results}

        Returns:
            AgentResult with Hermes's output and usage metrics.
        """
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")
        task_type = task.get("task_type", "")

        # Check availability
        available = await self.is_available()
        if not available:
            logger.warning("Hermes CLI not available, cannot execute task")
            return AgentResult(
                success=False,
                output="",
                error="Hermes Agent CLI is not installed. Install with: pip install hermes-agent",
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

        # Select toolsets based on task type
        toolsets = _TOOLSET_MAP.get(task_type)

        logger.info(
            "Hermes executing: task_id=%s type=%s goal=%s",
            task_id, task_type or "auto", goal[:80],
        )

        # Execute via Hermes CLI
        result = await self.client.run(
            prompt=goal,
            context=context_str,
        )

        if result.success:
            logger.info(
                "Hermes completed: task_id=%s tokens=%d+%d cost=$%.4f",
                task_id, result.input_tokens, result.output_tokens, result.cost,
            )
        else:
            error_summary = "; ".join(result.errors) if result.errors else "Unknown error"
            logger.warning(
                "Hermes failed: task_id=%s exit=%s errors=%s",
                task_id, result.exit_code, error_summary,
            )

        return AgentResult(
            success=result.success,
            output=result.output,
            artifacts=[],
            tokens_used=result.input_tokens + result.output_tokens,
            cost=result.cost,
            error="; ".join(result.errors) if result.errors else None,
        )
