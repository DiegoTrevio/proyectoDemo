"""Hermes Agent — delegates tasks to Nous Research's Hermes Agent (v0.4.0+).

Hermes excels at:
  - Complex multi-tool tasks (30+ native tools: terminal, files, web, git, browser, vision)
  - Tasks requiring persistent memory across sessions
  - Specialized skills (80+ loadable skills, including OCR, Huggingface, OSINT)
  - Multi-step autonomous execution with session resumption
  - OpenAI-compatible API server for structured HTTP communication

The Hermes agent acts as a bridge: it receives tasks from AgentOS's orchestrator
and delegates them to Hermes via HTTP API (preferred) or CLI subprocess (fallback).

Ported from: github.com/NousResearch/hermes-paperclip-adapter
"""

import logging

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from config.settings import settings
from tools.hermes_client import HermesClient, get_hermes_client
from tools.hermes_paperclip import PaperclipBridge, get_paperclip_bridge

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
    """Bridges AgentOS orchestrator to Hermes Agent (HTTP API or CLI).

    Supports two modes (auto-detected):
      1. HTTP API (v0.4.0+) — calls /v1/chat/completions endpoint
      2. CLI subprocess — spawns `hermes chat -q <prompt>`
    """

    name = "hermes"
    task_type = "multi"
    default_complexity = "complex"

    def __init__(
        self,
        client: HermesClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        paperclip_bridge: PaperclipBridge | None = None,
    ):
        cb_config = CircuitBreakerConfig(
            max_iterations=1,  # Hermes handles its own iterations internally
            timeout_seconds=600,  # 10 min max
            max_cost_per_task=5.0,
        )
        super().__init__(circuit_breaker or CircuitBreaker(cb_config))
        self._client = client
        self._paperclip = paperclip_bridge

    @property
    def client(self) -> HermesClient:
        if self._client is None:
            self._client = get_hermes_client()
        return self._client

    @property
    def paperclip(self) -> PaperclipBridge:
        if self._paperclip is None:
            self._paperclip = get_paperclip_bridge()
        return self._paperclip

    @property
    def use_paperclip(self) -> bool:
        return settings.hermes_paperclip_enabled

    async def is_available(self) -> bool:
        """Check if Hermes is accessible (HTTP API or CLI)."""
        try:
            return await self.client.is_available()
        except Exception:
            return False

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Execute a task via Hermes Agent.

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
            logger.warning("Hermes not available, cannot execute task")
            return AgentResult(
                success=False,
                output="",
                error=(
                    "Hermes Agent is not available. "
                    "Set HERMES_API_URL for HTTP mode or install CLI: pip install hermes-agent"
                ),
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

        mode = "paperclip" if self.use_paperclip else ("http" if self.client._use_http else "cli")
        logger.info(
            "Hermes executing: task_id=%s type=%s mode=%s goal=%s",
            task_id, task_type or "auto", mode, goal[:80],
        )

        # Execute via Paperclip adapter or direct Hermes
        if self.use_paperclip:
            result = await self.paperclip.assign_task(
                task_id=task_id,
                title=goal[:120],
                body=f"{context_str}\n\n{goal}" if context_str else goal,
                toolsets=toolsets,
            )
        else:
            result = await self.client.run(
                prompt=goal,
                context=context_str,
                toolsets=toolsets,
            )

        if result.success:
            logger.info(
                "Hermes completed: task_id=%s mode=%s tokens=%d+%d cost=$%.4f",
                task_id, result.mode, result.input_tokens, result.output_tokens, result.cost,
            )
        else:
            error_summary = "; ".join(result.errors) if result.errors else "Unknown error"
            logger.warning(
                "Hermes failed: task_id=%s mode=%s exit=%s errors=%s",
                task_id, result.mode, result.exit_code, error_summary,
            )

        return AgentResult(
            success=result.success,
            output=result.output,
            artifacts=[],
            tokens_used=result.input_tokens + result.output_tokens,
            cost=result.cost,
            error="; ".join(result.errors) if result.errors else None,
        )
