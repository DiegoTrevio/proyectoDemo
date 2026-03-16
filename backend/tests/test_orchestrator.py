"""Tests for the Orchestrator agent and supporting modules."""

import pytest

from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from agents.dispatcher import dispatch, get_available_agents


# ─── Circuit Breaker ──────────────────────────────────────────────────────

class TestCircuitBreaker:

    def test_new_state_is_not_tripped(self):
        cb = CircuitBreaker()
        state = cb.new_state()
        assert not state.tripped

    def test_token_limit_trips(self):
        cb = CircuitBreaker(CircuitBreakerConfig(max_tokens_per_task=100))
        state = cb.new_state()
        state = cb.record_usage(state, tokens=150, cost=0.0)
        assert state.tripped
        assert "Token limit" in state.trip_reason

    def test_iteration_limit_trips(self):
        cb = CircuitBreaker(CircuitBreakerConfig(max_iterations=2))
        state = cb.new_state()
        state = cb.record_usage(state, tokens=10, cost=0.0)
        state = cb.record_usage(state, tokens=10, cost=0.0)
        assert state.tripped
        assert "Iteration limit" in state.trip_reason

    def test_cost_limit_trips(self):
        cb = CircuitBreaker(CircuitBreakerConfig(max_cost_per_task=0.01))
        state = cb.new_state()
        state = cb.record_usage(state, tokens=10, cost=0.02)
        assert state.tripped
        assert "Cost limit" in state.trip_reason

    def test_within_limits_does_not_trip(self):
        cb = CircuitBreaker(CircuitBreakerConfig(
            max_tokens_per_task=10000,
            max_iterations=10,
            max_cost_per_task=5.0,
            timeout_seconds=300,
        ))
        state = cb.new_state()
        state = cb.record_usage(state, tokens=100, cost=0.001)
        assert not state.tripped

    def test_tripped_stays_tripped(self):
        cb = CircuitBreaker(CircuitBreakerConfig(max_tokens_per_task=100))
        state = cb.new_state()
        state = cb.record_usage(state, tokens=150, cost=0.0)
        assert state.tripped
        # Further checks should still be tripped
        state = cb.check(state)
        assert state.tripped


# ─── Dispatcher ───────────────────────────────────────────────────────────

class TestDispatcher:

    def test_available_agents(self):
        agents = get_available_agents()
        assert "researcher" in agents
        assert "coder" in agents
        assert "browser" in agents
        assert "document_writer" in agents
        assert "validator" in agents

    @pytest.mark.asyncio
    async def test_dispatch_researcher_stub(self):
        result = await dispatch("researcher", {"goal": "test query"}, {})
        assert result.success
        assert "researcher" in result.output.lower()
        assert "test query" in result.output

    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent_falls_back(self):
        result = await dispatch("nonexistent", {"goal": "test"}, {})
        assert result.success
        # Falls back to researcher
        assert "researcher" in result.output.lower()


# ─── Orchestrator Graph Structure ─────────────────────────────────────────

class TestOrchestratorGraph:

    def test_graph_compiles(self):
        from agents.orchestrator import build_orchestrator_graph
        graph = build_orchestrator_graph()
        assert graph is not None

    def test_graph_singleton(self):
        from agents.orchestrator import get_orchestrator
        g1 = get_orchestrator()
        g2 = get_orchestrator()
        assert g1 is g2

    def test_initial_state_shape(self):
        """Verify the initial state matches the expected TypedDict keys."""
        from agents.orchestrator import AgentState
        expected_keys = {
            "task_id", "goal", "task_type", "complexity", "plan",
            "current_step", "results", "errors", "memory_context",
            "iteration", "max_iterations", "final_output", "status", "cb_state",
        }
        # TypedDict annotations should have all expected keys
        assert set(AgentState.__annotations__.keys()) == expected_keys
