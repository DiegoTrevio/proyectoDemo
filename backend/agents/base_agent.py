"""Base agent class for all AgentOS agents.

Security flow (8 layers):
  REQUEST
   -> [1] LLM Guard scan_input (35 scanners)
   -> [2] Taint Tracker labels external content
   -> [3] NeMo Guardrails validates policies (Colang)
   -> [4] Policy Engine checks client rules
   -> AGENT EXECUTES (OBSERVE -> PLAN -> ACT -> REFLECT)
     -> [5a] Approval Gate for HIGH risk actions
     -> [5b] Taint check: tainted content can't trigger destructive tools
   -> [6] LLM Guard scan_output (20 scanners)
   -> [7] Merkle Audit records event in hash chain
   -> [8] Session Repair every 10 iterations
   -> RESPONSE

Each layer is independent — if one fails, others continue.
"""

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
    is_stub: bool = False


class AbstractAgent(ABC):
    """Base class for all AgentOS agents.

    Provides:
    - LiteLLM integration via model_router
    - Automatic Langfuse tracing
    - Circuit breaker enforcement
    - 8-layer security pipeline
    """

    name: str = "base"
    task_type: str = "code"
    default_complexity: str = "medium"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None):
        self.cb = circuit_breaker or CircuitBreaker()
        self._http = httpx.AsyncClient(base_url=LITELLM_BASE_URL, timeout=120)
        self._iteration_count = 0

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
        Runs the full 8-layer security pipeline.
        """
        if cb_state.tripped:
            return f"[Circuit breaker tripped: {cb_state.trip_reason}]", cb_state

        if model_override:
            model = model_override
        else:
            selection = select_model(self.task_type, self.default_complexity)
            model = selection.model

        task_id = cb_state.__dict__.get("task_id", "unknown")
        user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

        # ── [1] LLM Guard: scan input ──
        if user_text:
            try:
                from security.middleware import check_input_security
                sec_check = await check_input_security(
                    user_text, task_id=task_id, action="llm_call",
                )
                if not sec_check.allowed:
                    logger.warning("[Layer 1] Security blocked input: %s", sec_check.details)
                    return f"[Security blocked: {'; '.join(sec_check.details)}]", cb_state
                if sec_check.sanitized_input != user_text:
                    messages = [
                        {**m, "content": sec_check.sanitized_input}
                        if m is messages[-1] and m["role"] == "user" else m
                        for m in messages
                    ]
                    user_text = sec_check.sanitized_input
            except Exception as e:
                logger.warning("[Layer 1] LLM Guard input scan error (continuing): %s", e)

        # ── [2] Taint Tracker: label external content ──
        try:
            from security.taint_tracker import taint_tracker
            # Content coming from external context is labeled by the caller;
            # here we just check if current user_text has a taint label
            label = taint_tracker.get_label(user_text)
            if label:
                logger.debug("[Layer 2] Content has taint: source=%s trust=%.2f",
                             label.source.value, label.trust_level)
        except Exception as e:
            logger.warning("[Layer 2] Taint tracker error (continuing): %s", e)

        # ── [3] & [4] NeMo Guardrails + Policy Engine ──
        # These are already integrated in check_input_security via middleware

        # ── LLM call ──
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

        # ── [6] LLM Guard: scan output ──
        try:
            from security.middleware import check_output_security
            output_check = check_output_security(content, prompt=user_text, task_id=task_id)
            if output_check.sanitized_output != content:
                logger.info("[Layer 6] Security sanitized output: %s", output_check.details)
                content = output_check.sanitized_output
        except Exception as e:
            logger.warning("[Layer 6] LLM Guard output scan error (continuing): %s", e)

        # ── Usage tracking ──
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = input_tokens + output_tokens
        cost = total_tokens * 0.000003  # ~$3/1M tokens average

        cb_state = self.cb.record_usage(cb_state, total_tokens, cost)

        # ── [7] Merkle Audit: record event ──
        try:
            from security.merkle_audit import audit_chain
            audit_chain.add_event(
                task_id=task_id,
                agent_id=self.name,
                action="llm_call",
                input_data=user_text[:500],
                output_data=content[:500],
                model_used=model,
                tokens_used=total_tokens,
                cost=cost,
            )
        except Exception as e:
            logger.warning("[Layer 7] Merkle audit error (continuing): %s", e)

        # ── [8] Session Repair: periodic validation ──
        self._iteration_count += 1
        try:
            from security.session_repair import session_repair
            if session_repair.should_run(self._iteration_count):
                # Build minimal state for repair check
                repair_state = {
                    "task_id": task_id,
                    "goal": next((m["content"] for m in messages if m["role"] == "user"), ""),
                    "plan": [],
                    "results": [],
                    "errors": [],
                    "memory_context": {},
                    "iteration": self._iteration_count,
                    "final_output": "",
                }
                repair_result = session_repair.run_repair(repair_state)
                if not repair_result.healthy:
                    logger.warning(
                        "[Layer 8] Session repair found issues: %s",
                        repair_result.issues_found,
                    )
        except Exception as e:
            logger.warning("[Layer 8] Session repair error (continuing): %s", e)

        # ── Langfuse trace ──
        trace_request(
            task_id=task_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            duration_ms=duration_ms,
        )

        return content, cb_state

    async def validate_tool_call(self, task_id: str, tool_name: str, content: str = "") -> bool:
        """Validate a tool call through security layers [5a] and [5b].

        Call this before executing any tool/action.
        Returns True if allowed, raises on rejection.
        """
        # ── [5b] Taint check ──
        try:
            from security.taint_tracker import taint_tracker
            taint_tracker.validate_tool_call(content, tool_name)
        except Exception as e:
            if "TaintViolation" in type(e).__name__:
                raise
            logger.warning("[Layer 5b] Taint validation error: %s", e)

        # ── [5a] Approval gate ──
        try:
            from security.approval_gates import is_high_risk, request_approval, RiskLevel
            if is_high_risk(tool_name):
                from security.approval_gates import HIGH_RISK_ACTIONS
                reason = HIGH_RISK_ACTIONS.get(tool_name, f"Executing {tool_name}")
                approved = await request_approval(
                    task_id=task_id,
                    action=tool_name,
                    reason=reason,
                    risk_level=RiskLevel.HIGH,
                )
                if not approved:
                    raise PermissionError(
                        f"Action '{tool_name}' rejected by approval gate"
                    )
        except PermissionError:
            raise
        except Exception as e:
            logger.warning("[Layer 5a] Approval gate error (allowing): %s", e)

        return True

    async def close(self):
        await self._http.aclose()
