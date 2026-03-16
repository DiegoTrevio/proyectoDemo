"""Base agent class for all AgentOS agents."""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerState
from config.langfuse_client import trace_request
from config.model_router import LITELLM_BASE_URL, select_model
from config.settings import settings

logger = logging.getLogger("agentos.agents")


@dataclass
class AgentResult:
    """Standard result returned by every agent."""
    success: bool
    output: str
    artifacts: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    cost: float = 0.0
    error: str | None = None


class AbstractAgent(ABC):
    """Base class for all AgentOS agents.

    Provides:
    - LiteLLM integration via model_router
    - Automatic Langfuse tracing
    - Circuit breaker enforcement
    """

    name: str = "base"
    task_type: str = "code"
    default_complexity: str = "medium"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None):
        self.cb = circuit_breaker or CircuitBreaker()
        self._http = httpx.AsyncClient(base_url=LITELLM_BASE_URL, timeout=120)

    @abstractmethod
    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Execute the agent's primary task. Must be implemented by subclasses."""
        ...

    async def call_llm(
        self,
        messages: list[dict],
        cb_state: CircuitBreakerState,
        model_override: str | None = None,
        max_tokens: int = 4096,
    ) -> tuple[str, CircuitBreakerState]:
        """Call LiteLLM proxy and return (response_text, updated_cb_state).

        Automatically selects model via model_router unless overridden.
        Records usage in circuit breaker and Langfuse.
        """
        if cb_state.tripped:
            return f"[Circuit breaker tripped: {cb_state.trip_reason}]", cb_state

        if model_override:
            model = model_override
        else:
            selection = select_model(self.task_type, self.default_complexity)
            model = selection.model

        start = time.monotonic()
        resp = await self._http.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code != 200:
            logger.error("LLM call failed: %s %s", resp.status_code, resp.text[:200])
            return f"[LLM error: {resp.status_code}]", cb_state

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = input_tokens + output_tokens

        # Estimate cost (rough, per-token)
        cost = total_tokens * 0.000003  # ~$3/1M tokens average

        # Record in circuit breaker
        cb_state = self.cb.record_usage(cb_state, total_tokens, cost)

        # Trace in Langfuse
        trace_request(
            task_id=cb_state.__dict__.get("task_id", "unknown"),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            duration_ms=duration_ms,
        )

        return content, cb_state

    async def close(self):
        await self._http.aclose()
