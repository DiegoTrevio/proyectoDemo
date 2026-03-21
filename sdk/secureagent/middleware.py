"""Framework Middleware — integrate SecureAgent with popular AI agent frameworks.

Provides drop-in middleware for LangChain, CrewAI, and generic async agents.

Features:
- Taint context propagation in decorators
- PII blocking option in LangChain callback
- Input context extraction callbacks
"""

import functools
import logging
from typing import Any, Callable, Optional

from secureagent.core import SecureAgent, SecurityViolation

logger = logging.getLogger("secureagent.middleware")


class SecureLangChainCallback:
    """LangChain callback handler that routes tool calls through SecureAgent.

    Usage:
        from secureagent import SecureAgent
        from secureagent.middleware import SecureLangChainCallback

        agent = SecureAgent(...)
        callback = SecureLangChainCallback(agent, session_id="sess_123", block_pii=True)

        # Use with LangChain agent
        result = await langchain_agent.ainvoke(
            {"input": "..."},
            config={"callbacks": [callback]},
        )
    """

    def __init__(
        self,
        secure_agent: SecureAgent,
        session_id: str = "",
        agent_id: str = "langchain",
        block_pii: bool = False,
    ):
        self._agent = secure_agent
        self._session_id = session_id
        self._agent_id = agent_id
        self._block_pii = block_pii

    async def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        """Called when a LangChain tool starts."""
        tool_name = serialized.get("name", "unknown")
        logger.info("LangChain tool start: %s", tool_name)

        # Check PII in input
        pii_matches = self._agent.detect_pii(input_str)
        if pii_matches:
            pii_types = [m.type for m in pii_matches]
            logger.warning("PII in tool input '%s': %s", tool_name, pii_types)
            if self._block_pii:
                raise SecurityViolation(
                    f"PII detected in input for tool '{tool_name}': {pii_types}",
                    violation_type="pii_blocked",
                    details={"tool": tool_name, "pii_types": pii_types},
                )

    async def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Called when a LangChain tool ends."""
        pii_matches = self._agent.detect_pii(output)
        if pii_matches:
            logger.warning("PII in tool output: %s", [m.type for m in pii_matches])

    async def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        """Called when a LangChain tool errors."""
        logger.error("LangChain tool error: %s", error)


# Type for input context extractor
InputContextExtractor = Callable[..., str]


def _default_context_extractor(**kwargs: Any) -> str:
    """Default: extract first string arg as input context."""
    for value in kwargs.values():
        if isinstance(value, str) and len(value) > 10:
            return value
    return ""


def secure_tool(
    secure_agent: SecureAgent,
    session_id: str = "",
    agent_id: str = "default",
    input_context_extractor: Optional[InputContextExtractor] = None,
):
    """Decorator to wrap any async tool function with SecureAgent security.

    Args:
        secure_agent: The SecureAgent instance.
        session_id: Session ID for audit tracking.
        agent_id: Agent identifier.
        input_context_extractor: Optional callback to extract input_context
            from kwargs for taint tracking. Default extracts first string arg.

    Usage:
        @secure_tool(agent, session_id="sess_123")
        async def send_email(to: str, subject: str, body: str):
            return {"status": "sent"}

        result = await send_email(to="user@example.com", subject="Hi", body="Hello")
    """
    extractor = input_context_extractor or _default_context_extractor

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(**kwargs):
            input_context = ""
            try:
                input_context = extractor(**kwargs)
            except Exception as e:
                logger.debug("Input context extraction failed: %s", e)

            return await secure_agent.secure_call(
                tool_name=fn.__name__,
                tool_fn=fn,
                args=kwargs,
                agent_id=agent_id,
                session_id=session_id,
                input_context=input_context,
            )

        return wrapper
    return decorator


class SecureToolRegistry:
    """Registry for wrapping multiple tools with security.

    Usage:
        registry = SecureToolRegistry(agent, session_id="sess_123")

        registry.register("send_email", send_email_fn)
        registry.register("search", search_fn)

        result = await registry.call("send_email", to="user@example.com", body="Hi")
    """

    def __init__(self, secure_agent: SecureAgent, session_id: str = "", agent_id: str = "default"):
        self._agent = secure_agent
        self._session_id = session_id
        self._agent_id = agent_id
        self._tools: dict[str, Any] = {}

    def register(self, name: str, fn: Any) -> None:
        """Register a tool function."""
        if not callable(fn):
            raise TypeError(f"Tool function for '{name}' must be callable, got {type(fn)}")
        self._tools[name] = fn

    def unregister(self, name: str) -> bool:
        """Unregister a tool. Returns True if it existed."""
        return self._tools.pop(name, None) is not None

    async def call(self, name: str, input_context: str = "", **kwargs) -> Any:
        """Call a registered tool through the security pipeline."""
        fn = self._tools.get(name)
        if fn is None:
            raise ValueError(f"Tool '{name}' not registered. Available: {list(self._tools.keys())}")

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

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools
