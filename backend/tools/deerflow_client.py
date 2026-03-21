"""DeerFlow 2.0 client — communicates with DeerFlow Gateway API and LangGraph Server.

DeerFlow runs as a separate service in Docker:
  - Gateway API (port 8001): REST endpoints for models, memory, skills, artifacts, uploads
  - LangGraph Server (port 2024): Agent runtime, task execution, streaming

This client provides a clean async interface for AgentOS to delegate tasks to DeerFlow.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator

import httpx

from config.settings import settings

logger = logging.getLogger("agentos.tools.deerflow")


class DeerFlowTaskStatus(str, Enum):
    """Status of a DeerFlow task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DeerFlowEvent:
    """A streaming event from DeerFlow's LangGraph server."""
    event_type: str  # thought, action, result, error, artifact, status
    content: str
    agent: str = "deerflow"
    metadata: dict = field(default_factory=dict)


@dataclass
class DeerFlowResult:
    """Final result from a DeerFlow task execution."""
    success: bool
    output: str
    artifacts: list[dict] = field(default_factory=list)
    task_id: str = ""
    events: list[DeerFlowEvent] = field(default_factory=list)
    error: str | None = None


class DeerFlowClient:
    """Async client for DeerFlow 2.0 Gateway API and LangGraph Server.

    Usage:
        client = DeerFlowClient()
        result = await client.run_task("Research quantum computing breakthroughs in 2026")
        print(result.output)
    """

    def __init__(
        self,
        gateway_url: str | None = None,
        langgraph_url: str | None = None,
        timeout: float = 600,
    ):
        self.gateway_url = gateway_url or settings.deerflow_gateway_url
        self.langgraph_url = langgraph_url or settings.deerflow_langgraph_url
        self.timeout = timeout

    # ── Gateway API (port 8001) ───────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check if DeerFlow services are healthy."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                gw_resp = await client.get(f"{self.gateway_url}/health")
                lg_resp = await client.get(f"{self.langgraph_url}/ok")
                return gw_resp.status_code == 200 and lg_resp.status_code == 200
        except Exception as e:
            logger.debug("DeerFlow health check failed: %s", e)
            return False

    async def list_models(self) -> list[dict]:
        """List available models configured in DeerFlow."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.gateway_url}/api/models")
            resp.raise_for_status()
            return resp.json()

    async def list_skills(self) -> list[dict]:
        """List available DeerFlow skills."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.gateway_url}/api/skills")
            resp.raise_for_status()
            return resp.json()

    async def get_memory(self, user_id: str = "default") -> dict:
        """Retrieve DeerFlow's persistent memory for a user."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.gateway_url}/api/memory",
                params={"user_id": user_id},
            )
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            return resp.json()

    async def upload_file(self, filename: str, content: bytes, mime_type: str = "application/octet-stream") -> dict:
        """Upload a file to DeerFlow's workspace."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.gateway_url}/api/uploads",
                files={"file": (filename, content, mime_type)},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_artifact(self, task_id: str, artifact_path: str) -> bytes:
        """Download an artifact produced by a DeerFlow task."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.gateway_url}/api/artifacts/{task_id}",
                params={"path": artifact_path},
            )
            resp.raise_for_status()
            return resp.content

    # ── LangGraph Server (port 2024) ──────────────────────────────────────

    async def run_task(
        self,
        goal: str,
        skill: str | None = None,
        context: str = "",
        user_id: str = "default",
        config_overrides: dict | None = None,
    ) -> DeerFlowResult:
        """Run a task on DeerFlow and wait for completion.

        Args:
            goal: The task description / user goal.
            skill: Optional skill name to use (e.g., "research", "slides", "code").
            context: Additional context to provide to the agent.
            user_id: User ID for memory persistence.
            config_overrides: Optional DeerFlow config overrides.

        Returns:
            DeerFlowResult with output, artifacts, and event history.
        """
        events: list[DeerFlowEvent] = []
        output_parts: list[str] = []
        artifacts: list[dict] = []

        try:
            async for event in self.stream_task(goal, skill, context, user_id, config_overrides):
                events.append(event)

                if event.event_type == "result":
                    output_parts.append(event.content)
                elif event.event_type == "artifact":
                    artifacts.append(event.metadata)
                elif event.event_type == "error":
                    logger.warning("DeerFlow event error: %s", event.content)

            output = "\n\n".join(output_parts) if output_parts else ""

            # If no explicit result events, compile from all non-error events
            if not output:
                output = "\n".join(
                    e.content for e in events
                    if e.event_type in ("result", "action") and e.content
                )

            return DeerFlowResult(
                success=True,
                output=output or "DeerFlow task completed with no output.",
                artifacts=artifacts,
                events=events,
            )
        except Exception as e:
            logger.exception("DeerFlow task execution failed")
            return DeerFlowResult(
                success=False,
                output="",
                error=str(e),
                events=events,
            )

    async def stream_task(
        self,
        goal: str,
        skill: str | None = None,
        context: str = "",
        user_id: str = "default",
        config_overrides: dict | None = None,
    ) -> AsyncIterator[DeerFlowEvent]:
        """Stream events from a DeerFlow task execution.

        Connects to DeerFlow's LangGraph server SSE endpoint and yields events.
        """
        # Build the message payload for DeerFlow
        messages = []
        if context:
            messages.append({"role": "system", "content": context})

        user_content = goal
        if skill:
            user_content = f"[skill:{skill}] {goal}"

        messages.append({"role": "user", "content": user_content})

        payload = {
            "input": {"messages": messages},
            "config": {
                "configurable": {
                    "user_id": user_id,
                    **(config_overrides or {}),
                }
            },
            "stream_mode": "events",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.langgraph_url}/runs/stream",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # Strip "data: " prefix
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                        event = self._parse_event(data)
                        if event:
                            yield event
                    except json.JSONDecodeError:
                        continue

    def _parse_event(self, data: dict) -> DeerFlowEvent | None:
        """Parse a raw SSE event from DeerFlow into a DeerFlowEvent."""
        event_type = data.get("event", "")

        # LangGraph event types → normalized types
        if event_type == "on_chat_model_stream":
            content = data.get("data", {}).get("chunk", {}).get("content", "")
            if content:
                return DeerFlowEvent(event_type="thought", content=content)

        elif event_type == "on_tool_start":
            tool_name = data.get("name", "")
            tool_input = data.get("data", {}).get("input", "")
            return DeerFlowEvent(
                event_type="action",
                content=f"Using tool: {tool_name}",
                metadata={"tool": tool_name, "input": str(tool_input)[:500]},
            )

        elif event_type == "on_tool_end":
            output = data.get("data", {}).get("output", "")
            tool_name = data.get("name", "")

            # Check if this is a file/artifact output
            if tool_name in ("present_files", "write_file"):
                return DeerFlowEvent(
                    event_type="artifact",
                    content=f"Artifact from {tool_name}",
                    metadata={"tool": tool_name, "output": str(output)[:2000]},
                )

            return DeerFlowEvent(
                event_type="result",
                content=str(output)[:5000] if output else "",
                metadata={"tool": tool_name},
            )

        elif event_type in ("on_chain_end", "end"):
            output = data.get("data", {}).get("output", "")
            if isinstance(output, dict):
                messages = output.get("messages", [])
                if messages:
                    last_msg = messages[-1]
                    content = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
                    if content:
                        return DeerFlowEvent(event_type="result", content=content)

        elif event_type == "error":
            error_msg = data.get("data", {}).get("error", str(data))
            return DeerFlowEvent(event_type="error", content=str(error_msg))

        return None


# ── Singleton client ──────────────────────────────────────────────────────

_client: DeerFlowClient | None = None


def get_deerflow_client() -> DeerFlowClient:
    """Get or create the singleton DeerFlow client."""
    global _client
    if _client is None:
        _client = DeerFlowClient()
    return _client
