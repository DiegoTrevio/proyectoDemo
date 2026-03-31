"""Hermes Agent — delegates tasks to Nous Research's Hermes Agent (v0.6.0).

Hermes v0.6.0 is a REQUIRED SERVICE in AgentOS, providing:
  - 40+ native tools (terminal, files, web, git, browser, vision, code execution)
  - Multi-instance profiles (isolated config, memory, sessions, skills per project)
  - MCP server mode for IDE integration (Claude Desktop, VS Code, Cursor)
  - Ordered fallback provider chains for automatic LLM failover
  - Plugin lifecycle hooks and external skill directories
  - OpenAI-compatible API server for structured HTTP communication
  - Paperclip bridge for task management integration

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
    """Bridges AgentOS orchestrator to Hermes Agent v0.6.0 (HTTP API or CLI).

    v0.6.0 features:
      - Profile isolation: each task can run in a separate profile
      - MCP tool access: list and invoke Hermes tools via MCP protocol
      - Fallback providers: automatic LLM failover chain
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

    async def get_status(self) -> dict:
        """Get detailed Hermes status including profile and MCP info (v0.6.0+)."""
        available = await self.is_available()
        status = {
            "available": available,
            "mode": "http" if self.client._use_http else "cli",
            "profile": self.client.profile,
            "mcp_enabled": self.client.mcp_enabled,
            "fallback_providers": self.client.fallback_providers,
            "paperclip_enabled": self.use_paperclip,
        }
        if available:
            profile_info = await self.client.get_profile_info()
            if profile_info:
                status["profile_info"] = profile_info
            if self.client.mcp_enabled:
                mcp_tools = await self.client.mcp_list_tools()
                status["mcp_tools_count"] = len(mcp_tools)
        return status

    async def list_mcp_tools(self) -> list[dict]:
        """List tools available via Hermes MCP server (v0.6.0+)."""
        return await self.client.mcp_list_tools()

    async def call_mcp_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a Hermes MCP tool directly (v0.6.0+)."""
        return await self.client.mcp_call_tool(tool_name, arguments)

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Execute a task via Hermes Agent.

        Args:
            task: Dict with {goal, task_id, step_index, task_type?, profile?}
            context: Dict with {memory, prior_results}

        Returns:
            AgentResult with Hermes's output and usage metrics.
        """
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")
        task_type = task.get("task_type", "")
        task_profile = task.get("profile")  # v0.6.0: per-task profile override

        # Check availability
        available = await self.is_available()
        if not available:
            logger.warning("Hermes not available, cannot execute task")
            return AgentResult(
                success=False,
                output="",
                error=(
                    "Hermes Agent is not available. "
                    "Hermes is a required service — check that the hermes container is running."
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
            "Hermes executing: task_id=%s type=%s mode=%s profile=%s goal=%s",
            task_id, task_type or "auto", mode, task_profile or self.client.profile, goal[:80],
        )

        # Execute via Paperclip adapter or direct Hermes
        if self.use_paperclip:
            result = await self.paperclip.assign_task(
                task_id=task_id,
                title=goal[:120],
                body=f"{context_str}\n\n{goal}" if context_str else goal,
                toolsets=toolsets,
                profile=task_profile,
            )
        else:
            result = await self.client.run(
                prompt=goal,
                context=context_str,
                toolsets=toolsets,
                profile=task_profile,
            )

        if result.success:
            logger.info(
                "Hermes completed: task_id=%s mode=%s profile=%s tokens=%d+%d cost=$%.4f",
                task_id, result.mode, result.profile or "default",
                result.input_tokens, result.output_tokens, result.cost,
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
