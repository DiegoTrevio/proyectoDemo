"""Hermes Paperclip Adapter bridge — task management integration.

Bridges AgentOS task dispatch to Hermes via the Paperclip adapter protocol
(github.com/NousResearch/hermes-paperclip-adapter).

The Paperclip adapter enables Hermes to operate as an autonomous agent
with structured task assignment, session persistence, and progress reporting.

This module provides:
  - PaperclipBridge: sends tasks using the Paperclip adapter format
  - Template rendering for prompt injection (agentId, taskId, etc.)
"""

import logging
import re
from dataclasses import dataclass

from config.settings import settings
from tools.hermes_client import HermesClient, HermesResult, get_hermes_client

logger = logging.getLogger("agentos.tools.hermes_paperclip")

# Template variables supported by the Paperclip adapter
_TEMPLATE_VARS = {
    "agentId",
    "agentName",
    "companyId",
    "companyName",
    "runId",
    "taskId",
    "taskTitle",
    "taskBody",
    "projectName",
}

# Conditional section pattern: {{#varName}}content{{/varName}}
_CONDITIONAL_RE = re.compile(r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL)


@dataclass
class PaperclipTaskConfig:
    """Configuration for a Paperclip-style task assignment."""
    agent_id: str = "agentos-hermes"
    agent_name: str = "AgentOS Hermes Worker"
    company_id: str = "agentos"
    company_name: str = "AgentOS"
    max_iterations: int = 50
    timeout_sec: int = 300
    persist_session: bool = True
    enabled_toolsets: list[str] | None = None
    disabled_toolsets: list[str] | None = None
    prompt_template: str | None = None


def render_template(template: str, variables: dict[str, str]) -> str:
    """Render a Paperclip-style prompt template with variable substitution.

    Supports:
      - {{varName}} — simple substitution
      - {{#varName}}content{{/varName}} — conditional sections (included if var is truthy)
      - {{#noTask}}content{{/noTask}} — included when no taskId is set
    """
    result = template

    # Handle conditional sections
    def replace_conditional(match: re.Match) -> str:
        var_name = match.group(1)
        content = match.group(2)
        if var_name == "noTask":
            return content if not variables.get("taskId") else ""
        return content if variables.get(var_name) else ""

    result = _CONDITIONAL_RE.sub(replace_conditional, result)

    # Simple variable substitution
    for var_name in _TEMPLATE_VARS:
        result = result.replace(f"{{{{{var_name}}}}}", variables.get(var_name, ""))

    return result


class PaperclipBridge:
    """Bridge between AgentOS tasks and the Hermes Paperclip adapter protocol.

    Usage:
        bridge = PaperclipBridge()
        result = await bridge.assign_task(
            task_id="task-123",
            title="Research AI safety",
            body="Find the latest papers on AI alignment and summarize key findings.",
        )
    """

    def __init__(
        self,
        client: HermesClient | None = None,
        config: PaperclipTaskConfig | None = None,
    ):
        self._client = client
        self.config = config or PaperclipTaskConfig()

    @property
    def client(self) -> HermesClient:
        if self._client is None:
            self._client = get_hermes_client()
        return self._client

    async def assign_task(
        self,
        task_id: str,
        title: str,
        body: str,
        project_name: str = "",
        run_id: str | None = None,
        session_id: str | None = None,
        toolsets: list[str] | None = None,
    ) -> HermesResult:
        """Assign a task to Hermes using the Paperclip adapter protocol.

        Args:
            task_id: Unique task identifier.
            title: Short task title.
            body: Full task description/instructions.
            project_name: Optional project context.
            run_id: Optional run identifier for tracking.
            session_id: Optional session to resume.
            toolsets: Optional toolset override.

        Returns:
            HermesResult from execution.
        """
        variables = {
            "agentId": self.config.agent_id,
            "agentName": self.config.agent_name,
            "companyId": self.config.company_id,
            "companyName": self.config.company_name,
            "runId": run_id or "",
            "taskId": task_id,
            "taskTitle": title,
            "taskBody": body,
            "projectName": project_name,
        }

        # Render custom template or use default prompt
        if self.config.prompt_template:
            prompt = render_template(self.config.prompt_template, variables)
        else:
            prompt = self._default_prompt(title, body, project_name)

        logger.info(
            "Paperclip assigning task: id=%s title=%s project=%s",
            task_id, title[:60], project_name or "none",
        )

        return await self.client.run(
            prompt=prompt,
            session_id=session_id,
            toolsets=toolsets or self.config.enabled_toolsets,
        )

    def _default_prompt(self, title: str, body: str, project_name: str) -> str:
        """Build default Paperclip-style prompt."""
        parts = []
        if project_name:
            parts.append(f"Project: {project_name}")
        parts.append(f"Task: {title}")
        if body != title:
            parts.append(f"\n{body}")
        return "\n".join(parts)


# ── Singleton bridge ─────────────────────────────────────────────────────

_bridge: PaperclipBridge | None = None


def get_paperclip_bridge() -> PaperclipBridge:
    """Get or create the singleton Paperclip bridge."""
    global _bridge
    if _bridge is None:
        _bridge = PaperclipBridge()
    return _bridge
