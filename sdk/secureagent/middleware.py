"""Framework Middleware — integrate SecureAgent with popular AI agent frameworks.

Provides drop-in middleware for LangChain, CrewAI, and generic async agents.
"""

import logging
from typing import Any, Optional

from secureagent.core import SecureAgent

logger = logging.getLogger("secureagent.middleware")


class SecureLangChainCallback:
    """LangChain callback handler that routes tool calls through SecureAgent.

    Usage:
        from secureagent import SecureAgent
        from secureagent.middleware import SecureLangChainCallback

        agent = SecureAgent(...)
        callback = SecureLangChainCallback(agent, session_id="sess_123")

        # Use with LangChain agent
        result = await langchain_agent.ainvoke(
            {"input": "..."},
            config={"callbacks": [callback]},
        )
    """

    def __init__(self, secure_agent: SecureAgent, session_id: str = "", agent_id: str = "langchain"):
        self._agent = secure_agent
        self._session_id = session_id
        self._agent_id = agent_id

    async def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        """Called when a LangChain tool starts."""
        tool_name = serialized.get("name", "unknown")
        logger.info("LangChain tool start: %s", tool_name)

        # Check PII in input
        pii_matches = self._agent.detect_pii(input_str)
        if pii_matches:
            logger.warning("PII in tool input '%s': %s", tool_name, [m.type for m in pii_matches])

    async def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Called when a LangChain tool ends."""
        pii_matches = self._agent.detect_pii(output)
        if pii_matches:
            logger.warning("PII in tool output: %s", [m.type for m in pii_matches])

    async def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        """Called when a LangChain tool errors."""
        logger.error("LangChain tool error: %s", error)


def secure_tool(
    secure_agent: SecureAgent,
    session_id: str = "",
    agent_id: str = "default",
):
    """Decorator to wrap any async tool function with SecureAgent security.

    Usage:
        from secureagent import SecureAgent
        from secureagent.middleware import secure_tool

        agent = SecureAgent(approval_gates={"send_email": "high"})

        @secure_tool(agent, session_id="sess_123")
        async def send_email(to: str, subject: str, body: str):
            # ... send email logic ...
            return {"status": "sent"}

        # Now calling send_email goes through the security pipeline
        result = await send_email(to="user@example.com", subject="Hi", body="Hello")
    """
    def decorator(fn):
        import functools

        @functools.wraps(fn)
        async def wrapper(**kwargs):
            return await secure_agent.secure_call(
                tool_name=fn.__name__,
                tool_fn=fn,
                args=kwargs,
                agent_id=agent_id,
                session_id=session_id,
            )

        return wrapper
    return decorator


class SecureToolRegistry:
    """Registry for wrapping multiple tools with security.

    Usage:
        from secureagent import SecureAgent
        from secureagent.middleware import SecureToolRegistry

        agent = SecureAgent(
            approval_gates={"send_email": "high", "search": "low"},
        )
        registry = SecureToolRegistry(agent, session_id="sess_123")

        # Register tools
        registry.register("send_email", send_email_fn)
        registry.register("search", search_fn)

        # Call through registry (goes through security pipeline)
        result = await registry.call("send_email", to="user@example.com", body="Hi")
    """

    def __init__(self, secure_agent: SecureAgent, session_id: str = "", agent_id: str = "default"):
        self._agent = secure_agent
        self._session_id = session_id
        self._agent_id = agent_id
        self._tools: dict[str, Any] = {}

    def register(self, name: str, fn: Any) -> None:
        """Register a tool function."""
        self._tools[name] = fn

    async def call(self, name: str, input_context: str = "", **kwargs) -> Any:
        """Call a registered tool through the security pipeline."""
        fn = self._tools.get(name)
        if fn is None:
            raise ValueError(f"Tool '{name}' not registered")

        return await self._agent.secure_call(
            tool_name=name,
            tool_fn=fn,
            args=kwargs,
            agent_id=self._agent_id,
            session_id=self._session_id,
            input_context=input_context,
        )

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())
