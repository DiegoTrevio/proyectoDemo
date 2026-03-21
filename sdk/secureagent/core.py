"""SecureAgent — Main entry point for the SDK.

Wraps any AI agent's tool calls with enterprise security:
taint tracking, PII detection, audit trails, and approval gates.
"""

import logging
import uuid
from typing import Any, Callable, Coroutine, Optional

from secureagent.audit import AuditLog
from secureagent.cloud import CloudClient
from secureagent.gates import ApprovalCallback, ApprovalGate, RiskLevel
from secureagent.pii import PIIDetector
from secureagent.taint import TaintSource, TaintTracker, TaintViolation

logger = logging.getLogger("secureagent")


class SecurityViolation(Exception):
    """Raised when a security check fails."""

    def __init__(self, message: str, violation_type: str, details: Optional[dict] = None):
        self.violation_type = violation_type
        self.details = details or {}
        super().__init__(message)


class SecureAgent:
    """Enterprise security wrapper for AI agent tool calls.

    Usage:
        from secureagent import SecureAgent

        agent = SecureAgent(
            taint_tracking=True,
            pii_detection=True,
            audit_log=True,
            approval_gates={"send_email": "high", "search_web": "low"},
            cloud_api_key="sk-...",  # Optional: send to dashboard
        )

        # Secure a tool call
        result = await agent.secure_call(
            tool_name="send_email",
            tool_fn=my_send_email_function,
            args={"to": "user@example.com", "body": "Hello"},
            agent_id="email_agent",
            session_id="sess_123",
        )

        # Check for PII before sending to LLM
        clean_text = agent.redact_pii("My email is john@test.com")

        # Export audit trail
        trail = agent.export_audit("sess_123")

        # Verify audit chain integrity
        valid, msg = agent.verify_audit("sess_123")
    """

    def __init__(
        self,
        taint_tracking: bool = True,
        pii_detection: bool = True,
        audit_log: bool = True,
        approval_gates: Optional[dict[str, str]] = None,
        approval_callback: Optional[ApprovalCallback] = None,
        approval_timeout: int = 300,
        block_pii_in_output: bool = False,
        cloud_api_key: Optional[str] = None,
        cloud_base_url: Optional[str] = None,
        custom_destructive_tools: Optional[set[str]] = None,
    ):
        # Taint tracking
        self._taint_enabled = taint_tracking
        self._taint = TaintTracker(custom_destructive_tools=custom_destructive_tools) if taint_tracking else None

        # PII detection
        self._pii_enabled = pii_detection
        self._pii = PIIDetector() if pii_detection else None
        self._block_pii_output = block_pii_in_output

        # Audit log
        self._audit_enabled = audit_log
        self._audit = AuditLog() if audit_log else None

        # Approval gates
        self._gates = ApprovalGate(
            risk_map=approval_gates,
            approval_callback=approval_callback,
            timeout=approval_timeout,
        ) if approval_gates is not None else None

        # Cloud client
        self._cloud = None
        if cloud_api_key:
            self._cloud = CloudClient(
                api_key=cloud_api_key,
                base_url=cloud_base_url,
            )

    async def secure_call(
        self,
        tool_name: str,
        tool_fn: Callable[..., Coroutine[Any, Any, Any]],
        args: Optional[dict] = None,
        agent_id: str = "default",
        session_id: str = "",
        input_context: str = "",
        model_used: str = "",
    ) -> Any:
        """Execute a tool call through the full security pipeline.

        Pipeline order:
        1. PII scan on input args
        2. Taint validation (if input context is tainted)
        3. Approval gate check
        4. Execute tool
        5. PII scan on output (optional blocking)
        6. Audit log
        7. Cloud event (if configured)

        Returns the tool function result.
        Raises SecurityViolation if any check fails.
        """
        session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        args = args or {}

        # 1. PII scan on input
        if self._pii_enabled and self._pii:
            for key, value in args.items():
                if isinstance(value, str) and self._pii.contains_pii(value):
                    pii_matches = self._pii.detect(value)
                    pii_types = [m.type for m in pii_matches]
                    logger.warning(
                        "PII detected in arg '%s' for tool '%s': %s",
                        key, tool_name, pii_types,
                    )
                    self._emit_cloud_event("pii_detected", tool_name, session_id, agent_id, {
                        "arg": key,
                        "pii_types": pii_types,
                    })

        # 2. Taint validation
        if self._taint_enabled and self._taint and input_context:
            try:
                self._taint.validate_tool_call(input_context, tool_name)
            except TaintViolation as e:
                self._log_audit(session_id, agent_id, "taint_violation", tool_name, str(e), "", "high")
                self._emit_cloud_event("taint_violation", tool_name, session_id, agent_id, {
                    "source": e.label.source.value if e.label else "unknown",
                })
                raise SecurityViolation(
                    str(e),
                    violation_type="taint",
                    details={"tool": tool_name, "source": e.label.source.value if e.label else "unknown"},
                ) from e

        # 3. Approval gate
        if self._gates:
            approved = await self._gates.check(
                tool_name=tool_name,
                session_id=session_id,
                params=args,
            )
            if not approved:
                self._log_audit(session_id, agent_id, "approval_rejected", tool_name, "", "", "high")
                self._emit_cloud_event("approval_rejected", tool_name, session_id, agent_id)
                raise SecurityViolation(
                    f"Tool '{tool_name}' requires approval — rejected or timed out",
                    violation_type="approval",
                    details={"tool": tool_name},
                )

        # 4. Execute tool
        try:
            result = await tool_fn(**args)
        except Exception as e:
            self._log_audit(session_id, agent_id, "tool_error", tool_name, str(args), str(e), "medium")
            self._emit_cloud_event("tool_error", tool_name, session_id, agent_id, {"error": str(e)})
            raise

        # 5. PII scan on output
        result_str = str(result) if result is not None else ""
        if self._pii_enabled and self._pii and result_str:
            if self._pii.contains_pii(result_str):
                pii_matches = self._pii.detect(result_str)
                logger.warning("PII in output of '%s': %s", tool_name, [m.type for m in pii_matches])
                if self._block_pii_output:
                    result_str = self._pii.redact(result_str)

        # 6. Audit log
        risk = self._gates.get_risk(tool_name).value if self._gates else "low"
        self._log_audit(
            session_id, agent_id, "tool_call", tool_name,
            str(args), result_str[:500], risk, model_used,
        )

        # 7. Cloud event
        self._emit_cloud_event("tool_call", tool_name, session_id, agent_id, {
            "risk": risk,
            "model": model_used,
        })

        return result

    # ─── Convenience methods ─────────────────────────────────────────────

    def label_content(
        self,
        content: str,
        source: TaintSource,
        trust_level: float = 0.0,
        original_source: str = "",
    ):
        """Label external content as tainted."""
        if self._taint:
            return self._taint.label(content, source, trust_level, original_source)

    def approve_content(self, content: str, approved_by: str) -> bool:
        """Manually approve tainted content for destructive actions."""
        if self._taint:
            return self._taint.launder(content, approved_by)
        return False

    def detect_pii(self, text: str):
        """Detect PII in text."""
        if self._pii:
            return self._pii.detect(text)
        return []

    def redact_pii(self, text: str) -> str:
        """Redact PII from text."""
        if self._pii:
            return self._pii.redact(text)
        return text

    def export_audit(self, session_id: str) -> list[dict]:
        """Export audit trail for a session (SOC2/GDPR)."""
        if self._audit:
            return self._audit.export_chain(session_id)
        return []

    def verify_audit(self, session_id: str) -> tuple[bool, str]:
        """Verify audit chain integrity."""
        if self._audit:
            return self._audit.verify_chain(session_id)
        return True, "Audit disabled"

    def get_audit_stats(self, session_id: str) -> dict:
        """Get audit statistics for a session."""
        if self._audit:
            return self._audit.get_stats(session_id)
        return {}

    async def close(self):
        """Close cloud client and flush remaining events."""
        if self._cloud:
            await self._cloud.close()

    # ─── Internal helpers ────────────────────────────────────────────────

    def _log_audit(
        self,
        session_id: str,
        agent_id: str,
        action: str,
        tool_name: str,
        input_data: str = "",
        output_data: str = "",
        risk_level: str = "low",
        model_used: str = "",
    ):
        if self._audit:
            self._audit.add_event(
                session_id=session_id,
                agent_id=agent_id,
                action=action,
                tool_name=tool_name,
                input_data=input_data,
                output_data=output_data,
                risk_level=risk_level,
                model_used=model_used,
            )

    def _emit_cloud_event(
        self,
        event_type: str,
        tool_name: str,
        session_id: str,
        agent_id: str,
        extra: Optional[dict] = None,
    ):
        if self._cloud:
            self._cloud.send_event({
                "type": event_type,
                "tool_name": tool_name,
                "session_id": session_id,
                "agent_id": agent_id,
                **(extra or {}),
            })
