"""Langfuse observability client for AgentOS."""

import logging

from config.settings import settings

logger = logging.getLogger("agentos.langfuse")

langfuse = None


def init_langfuse():
    """Initialize Langfuse client. Returns None if keys are not configured or langfuse is not installed."""
    global langfuse
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    try:
        from langfuse import Langfuse
        langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except ImportError:
        logger.warning("langfuse package not installed — tracing disabled")
    return langfuse


def trace_request(task_id: str, model: str, input_tokens: int, output_tokens: int,
                  cost: float, duration_ms: int) -> None:
    """Record a model invocation trace in Langfuse."""
    if langfuse is None:
        return
    trace = langfuse.trace(name="task_execution", metadata={"task_id": task_id})
    trace.generation(
        name="llm_call",
        model=model,
        usage={"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens},
        metadata={"cost": cost, "duration_ms": duration_ms, "task_id": task_id},
    )
