"""SecureAgent — Main entry point for the SDK.

Wraps any AI agent's tool calls with enterprise security:
taint tracking, PII detection, audit trails, and approval gates.

Features:
- Input validation on tool names and args
- Configurable audit signing
- Taint strict mode support
- Output truncation with indicator
"""

import logging
import re
import uuid
from typing import Any, Callable, Coroutine, Optional

from secureagent.audit import AuditLog, StorageBackend
from secureagent.cloud import CloudClient
from secureagent.gates import ApprovalCallback, ApprovalGate, RiskLevel
from secureagent.pii import PIIDetector
from secureagent.taint import TaintSource, TaintTracker, TaintViolation

logger = logging.getLogger("secureagent")

# Validation patterns
_TOOL_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_.\-]{1,100}$')
_MAX_ARG_VALUE_SIZE = 50_000  # 50KB per arg value
_MAX_AUDIT_OUTPUT_SIZE = 2000  # Truncate output for audit at 2KB


class SecurityViolation(Exception):
    """Raised when a security check fails."""

    def __init__(self, message: str, violation_type: str, details: Optional[dict] = None):
        self.violation_type = violation_type
        self.details = details or {}
        super().__init__(message)


def _validate_tool_name(tool_name: str) -> str:
    """Validate tool name format."""
    if not tool_name:
        raise ValueError("tool_name cannot be empty")
    if not _TOOL_NAME_PATTERN.match(tool_name):
        raise ValueError(
            f"Invalid tool_name '{tool_name[:50]}': must match [a-zA-Z0-9_.\\-]{{1,100}}"
        )
    return tool_name


def _truncate(text: str, max_size: int, label: str = "") -> str:
    """Truncate text with indicator if too long."""
    if len(text) <= max_size:
        return text
    suffix = f" [TRUNCATED from {len(text)} chars]"
    if label:
        suffix = f" [TRUNCATED {label} from {len(text)} chars]"
    return text[:max_size - len(suffix)] + suffix


class SecureAgent:
    """Enterprise security wrapper for AI agent tool calls.

    Usage:
        from secureagent import SecureAgent

        agent = SecureAgent(
            taint_tracking=True,
            pii_detection=True,
            audit_log=True,
            approval_gates={"send_email": "high", "search_web": "low"},
            audit_signing_key="your-secret",  # HMAC signing
            taint_strict_mode=True,            # Block unknown content
            cloud_api_key="sk-...",            # Optional dashboard
        )

        result = await agent.secure_call(
            tool_name="send_email",
            tool_fn=my_send_email_function,
            args={"to": "user@example.com", "body": "Hello"},
            agent_id="email_agent",
            session_id="sess_123",
        )
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
        # New hardening options
        audit_signing_key: Optional[str] = None,
        audit_storage: Optional[StorageBackend] = None,
        audit_max_events: int = 10_000,
        taint_strict_mode: bool = False,
        taint_salt: Optional[str] = None,
        taint_max_entries: int = 50_000,
        taint_ttl_seconds: int = 3600,
    ):
        # Taint tracking
        self._taint_enabled = taint_tracking
        self._taint = TaintTracker(
            custom_destructive_tools=custom_destructive_tools,
            strict_mode=taint_strict_mode,
            salt=taint_salt,
            max_entries=taint_max_entries,
            ttl_seconds=taint_ttl_seconds,
        ) if taint_tracking else None

        # PII detection
        self._pii_enabled = pii_detection
        self._pii = PIIDetector() if pii_detection else None
        self._block_pii_output = block_pii_in_output

        # Audit log
        self._audit_enabled = audit_log
        self._audit = AuditLog(
            signing_key=audit_signing_key,
            storage=audit_storage,
            max_events_per_session=audit_max_events,
        ) if audit_log else None

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
        1. Validate inputs (tool_name, args)
        2. PII scan on input args
        3. Taint validation (if input context is tainted)
        4. Approval gate check
        5. Execute tool
        6. PII scan on output (optional blocking)
        7. Audit log
        8. Cloud event (if configured)

        Returns the tool function result.
        Raises SecurityViolation if any check fails.
        Raises ValueError if inputs are invalid.
        """
        # 0. Validate inputs
        _validate_tool_name(tool_name)
        session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        args = args or {}

        # Validate arg values aren't excessively large
        for key, value in args.items():
            if isinstance(value, str) and len(value) > _MAX_ARG_VALUE_SIZE:
                logger.warning(
                    "Arg '%s' for tool '%s' is %d bytes (max %d) — truncating for audit only",
                    key, tool_name, len(value), _MAX_ARG_VALUE_SIZE,
                )

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
            error_msg = _truncate(str(e), 500)
            args_str = _truncate(str(args), 500)
            self._log_audit(session_id, agent_id, "tool_error", tool_name, args_str, error_msg, "medium")
            self._emit_cloud_event("tool_error", tool_name, session_id, agent_id, {"error": error_msg})
            raise

        # 5. PII scan on output
        result_str = _truncate(str(result), _MAX_AUDIT_OUTPUT_SIZE) if result is not None else ""
        if self._pii_enabled and self._pii and result_str:
            if self._pii.contains_pii(result_str):
                pii_matches = self._pii.detect(result_str)
                logger.warning("PII in output of '%s': %s", tool_name, [m.type for m in pii_matches])
                if self._block_pii_output:
                    result_str = self._pii.redact(result_str)

        # 6. Audit log
        risk = self._gates.get_risk(tool_name).value if self._gates else "low"
        args_str = _truncate(str(args), _MAX_AUDIT_OUTPUT_SIZE)
        self._log_audit(
            session_id, agent_id, "tool_call", tool_name,
            args_str, result_str, risk, model_used,
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
