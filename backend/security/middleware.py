"""Security middleware — wraps LLM calls with guardrails, scanning, and policy checks.

Flow integration:
  BEFORE each LLM call: scan_input + check_policy
  AFTER each LLM response: scan_output
  If NeMo detects violation: block and return error
  Everything traced in Langfuse with tag "security"
"""

import logging
from dataclasses import dataclass, field

from config.langfuse_client import langfuse
from security.llm_guard_config import ScanResult, scan_input, scan_output
from security.policy_engine import PolicyDecision, check_policy

logger = logging.getLogger("agentos.security.middleware")


@dataclass
class SecurityCheckResult:
    """Combined result of all security checks."""
    allowed: bool
    sanitized_input: str
    risks: dict[str, float] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)
    policy_decision: PolicyDecision | None = None
    input_scan: ScanResult | None = None


@dataclass
class OutputCheckResult:
    """Result of output security scan."""
    sanitized_output: str
    is_safe: bool
    risks: dict[str, float] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)


async def check_input_security(
    text: str,
    client_id: str = "default",
    action: str = "llm_call",
    context: dict | None = None,
    task_id: str = "unknown",
) -> SecurityCheckResult:
    """Run all input security checks before an LLM call.

    1. LLM Guard input scan (PII, injection, toxicity)
    2. Policy engine check (allowed actions, topics, cost)

    Args:
        text: The user input / prompt text.
        client_id: Client/tenant ID for policy lookup.
        action: The action being performed.
        context: Additional context (topic, cost, etc.)
        task_id: For Langfuse tracing.

    Returns:
        SecurityCheckResult with combined assessment.
    """
    context = context or {}
    all_risks: dict[str, float] = {}
    all_details: list[str] = []

    # ── Step 1: LLM Guard input scan ──
    input_scan = scan_input(text)
    all_risks.update(input_scan.risks)
    all_details.extend(input_scan.details)

    if not input_scan.is_safe:
        _trace_security_event(task_id, "input_blocked", input_scan.risks, input_scan.details)

        # Prompt injection is a hard block
        if "PromptInjection" in input_scan.risks:
            return SecurityCheckResult(
                allowed=False,
                sanitized_input="",
                risks=all_risks,
                details=["Prompt injection detected — request blocked"],
                input_scan=input_scan,
            )

    # ── Step 2: Policy check ──
    policy_decision = await check_policy(client_id, action, context)
    if not policy_decision.allowed:
        all_details.append(f"Policy: {policy_decision.reason}")
        _trace_security_event(task_id, "policy_blocked", {}, [policy_decision.reason])
        return SecurityCheckResult(
            allowed=False,
            sanitized_input=input_scan.sanitized_text,
            risks=all_risks,
            details=all_details,
            policy_decision=policy_decision,
            input_scan=input_scan,
        )

    if policy_decision.requires_approval:
        all_details.append(f"Approval required: {policy_decision.reason}")

    # ── Trace ──
    if all_risks:
        _trace_security_event(task_id, "input_scanned", all_risks, all_details)

    return SecurityCheckResult(
        allowed=True,
        sanitized_input=input_scan.sanitized_text,
        risks=all_risks,
        details=all_details,
        policy_decision=policy_decision,
        input_scan=input_scan,
    )


def check_output_security(
    text: str,
    prompt: str = "",
    task_id: str = "unknown",
) -> OutputCheckResult:
    """Run output security checks after an LLM response.

    1. LLM Guard output scan (PII leakage, sensitive data)

    Args:
        text: The LLM response text.
        prompt: The original prompt (for relevance checking).
        task_id: For Langfuse tracing.

    Returns:
        OutputCheckResult with sanitized output and risk assessment.
    """
    output_scan = scan_output(text, prompt)

    if not output_scan.is_safe:
        _trace_security_event(task_id, "output_sanitized", output_scan.risks, output_scan.details)

    return OutputCheckResult(
        sanitized_output=output_scan.sanitized_text,
        is_safe=output_scan.is_safe,
        risks=output_scan.risks,
        details=output_scan.details,
    )


# ─── NeMo Guardrails integration ─────────────────────────────────────────

_guardrails_runnable = None


def get_guardrails_runnable():
    """Get or create NeMo Guardrails RunnableRails instance."""
    global _guardrails_runnable
    if _guardrails_runnable is not None:
        return _guardrails_runnable

    try:
        from nemoguardrails import RailsConfig
        from nemoguardrails.integrations.langchain import RunnableRails

        config = RailsConfig.from_path("backend/security/guardrails_config")
        _guardrails_runnable = RunnableRails(config)
        logger.info("NeMo Guardrails initialized")
        return _guardrails_runnable
    except ImportError:
        logger.warning("nemoguardrails not installed — guardrails disabled")
        return None
    except Exception as e:
        logger.warning("Failed to init NeMo Guardrails: %s", e)
        return None


async def apply_guardrails(messages: list[dict]) -> tuple[list[dict], bool]:
    """Apply NeMo Guardrails to messages.

    Returns:
        (processed_messages, was_blocked) — if blocked, messages will contain the refusal.
    """
    runnable = get_guardrails_runnable()
    if runnable is None:
        return messages, False

    try:
        result = await runnable.ainvoke({"messages": messages})
        output_messages = result.get("messages", messages)

        # Check if guardrails blocked the request
        blocked = False
        for msg in output_messages:
            content = msg.get("content", "").lower()
            if "cannot comply" in content or "action has been cancelled" in content:
                blocked = True
                break

        return output_messages, blocked
    except Exception as e:
        logger.warning("Guardrails processing failed: %s", e)
        return messages, False


# ─── Langfuse tracing ────────────────────────────────────────────────────

def _trace_security_event(
    task_id: str,
    event_type: str,
    risks: dict,
    details: list[str],
) -> None:
    """Trace a security event in Langfuse."""
    if langfuse is None:
        return

    try:
        trace = langfuse.trace(
            name="security_check",
            metadata={"task_id": task_id, "tags": ["security"]},
        )
        trace.event(
            name=event_type,
            metadata={
                "risks": risks,
                "details": details,
                "task_id": task_id,
            },
        )
    except Exception:
        pass  # Don't let tracing failures affect security flow
