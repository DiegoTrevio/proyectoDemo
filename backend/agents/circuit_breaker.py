"""Circuit breaker for AgentOS agents.

Enforces hard limits on tokens, iterations, cost, and time per task
to prevent runaway LLM loops.
"""

import time
from dataclasses import dataclass, field


@dataclass
class CircuitBreakerConfig:
    max_tokens_per_task: int = 500_000
    max_iterations: int = 10
    timeout_seconds: int = 300  # 5 min per iteration
    max_cost_per_task: float = 5.00


@dataclass
class CircuitBreakerState:
    """Mutable state tracked across a task's lifetime."""
    tokens_used: int = 0
    iterations: int = 0
    total_cost: float = 0.0
    start_time: float = field(default_factory=time.monotonic)
    tripped: bool = False
    trip_reason: str = ""


class CircuitBreaker:
    """Checks resource limits before each agent iteration."""

    def __init__(self, config: CircuitBreakerConfig | None = None):
        self.config = config or CircuitBreakerConfig()

    def new_state(self) -> CircuitBreakerState:
        return CircuitBreakerState()

    def check(self, state: CircuitBreakerState) -> CircuitBreakerState:
        """Check all limits. Sets state.tripped=True with reason if any limit exceeded."""
        if state.tripped:
            return state

        if state.tokens_used >= self.config.max_tokens_per_task:
            state.tripped = True
            state.trip_reason = (
                f"Token limit exceeded: {state.tokens_used:,} >= {self.config.max_tokens_per_task:,}"
            )
        elif state.iterations >= self.config.max_iterations:
            state.tripped = True
            state.trip_reason = (
                f"Iteration limit exceeded: {state.iterations} >= {self.config.max_iterations}"
            )
        elif state.total_cost >= self.config.max_cost_per_task:
            state.tripped = True
            state.trip_reason = (
                f"Cost limit exceeded: ${state.total_cost:.4f} >= ${self.config.max_cost_per_task:.2f}"
            )
        elif (time.monotonic() - state.start_time) >= self.config.timeout_seconds:
            state.tripped = True
            state.trip_reason = (
                f"Timeout exceeded: {self.config.timeout_seconds}s"
            )

        return state

    def record_usage(self, state: CircuitBreakerState, tokens: int, cost: float) -> CircuitBreakerState:
        """Record token/cost usage and increment iteration count."""
        state.tokens_used += tokens
        state.total_cost += cost
        state.iterations += 1
        return self.check(state)
