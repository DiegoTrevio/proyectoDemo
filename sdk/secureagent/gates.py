"""Approval Gates — blocks irreversible actions until human approval.

Actions classified as HIGH risk are blocked until explicit approval via
callback function. MEDIUM risk actions are logged. LOW risk passes through.

Features:
- Bounded history with configurable max size
- Validated risk level inputs
- Session-isolated approval tracking
"""

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("secureagent.gates")


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ApprovalRequest:
    """Represents a pending approval."""
    id: str
    session_id: str
    action: str
    tool_name: str
    reason: str
    risk_level: RiskLevel
    params: dict = field(default_factory=dict)
    created_at: str = ""
    status: str = "pending"  # pending, approved, rejected, timeout

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "action": self.action,
            "tool_name": self.tool_name,
            "reason": self.reason,
            "risk_level": self.risk_level.value,
            "params": self.params,
            "created_at": self.created_at,
            "status": self.status,
        }


# Type for approval callback
ApprovalCallback = Callable[[ApprovalRequest], Coroutine[Any, Any, bool]]


# Default risk classification for common tools
DEFAULT_RISK_MAP: dict[str, RiskLevel] = {
    "send_email": RiskLevel.HIGH,
    "make_payment": RiskLevel.HIGH,
    "delete_file": RiskLevel.HIGH,
    "delete_data": RiskLevel.HIGH,
    "publish_content": RiskLevel.HIGH,
    "push_code": RiskLevel.HIGH,
    "create_pr": RiskLevel.HIGH,
    "update_crm": RiskLevel.HIGH,
    "send_message": RiskLevel.MEDIUM,
    "drop_table": RiskLevel.HIGH,
    "execute_code": RiskLevel.HIGH,
    "modify_database": RiskLevel.HIGH,
    "search_web": RiskLevel.LOW,
    "read_file": RiskLevel.LOW,
    "list_files": RiskLevel.LOW,
}


class ApprovalGate:
    """Gates agent actions behind human approval based on risk level.

    Usage:
        gate = ApprovalGate(
            risk_map={"send_email": "high", "search": "low"},
            approval_callback=my_approval_handler,
            timeout=300,
            max_history=5000,
        )

        # Check if action is allowed
        allowed = await gate.check("send_email", session_id="sess_123", params={...})
    """

    def __init__(
        self,
        risk_map: Optional[dict[str, str]] = None,
        approval_callback: Optional[ApprovalCallback] = None,
        timeout: int = 300,
        max_history: int = 5000,
    ):
        # Defensive copy of default risk map
        self._risk_map: dict[str, RiskLevel] = dict(DEFAULT_RISK_MAP)
        if risk_map:
            for tool, level in risk_map.items():
                try:
                    self._risk_map[tool] = RiskLevel(level.lower())
                except ValueError:
                    logger.warning("Invalid risk level '%s' for tool '%s', defaulting to MEDIUM", level, tool)
                    self._risk_map[tool] = RiskLevel.MEDIUM

        self._callback = approval_callback
        self._timeout = timeout
        self._history: deque[ApprovalRequest] = deque(maxlen=max_history)

    def set_risk(self, tool_name: str, level: str) -> None:
        """Set risk level for a tool."""
        try:
            self._risk_map[tool_name] = RiskLevel(level.lower())
        except ValueError:
            logger.warning("Invalid risk level '%s', defaulting to MEDIUM", level)
            self._risk_map[tool_name] = RiskLevel.MEDIUM

    def get_risk(self, tool_name: str) -> RiskLevel:
        """Get risk level for a tool. Defaults to MEDIUM for unknown tools."""
        return self._risk_map.get(tool_name, RiskLevel.MEDIUM)

    async def check(
        self,
        tool_name: str,
        session_id: str = "",
        params: Optional[dict] = None,
        reason: str = "",
    ) -> bool:
        """Check if a tool call is allowed.

        LOW: Always allowed, logged.
        MEDIUM: Always allowed, logged with warning.
        HIGH: Blocked until approval callback returns True, or timeout.

        Returns True if allowed, False if rejected/timeout.
        """
        risk = self.get_risk(tool_name)

        # Sanitize params for logging (truncate values)
        safe_params = {}
        if params:
            for k, v in params.items():
                safe_params[str(k)[:50]] = str(v)[:200]

        request = ApprovalRequest(
            id=f"apr_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            action="tool_call",
            tool_name=tool_name,
            reason=reason or f"Agent wants to call '{tool_name}'",
            risk_level=risk,
            params=safe_params,
        )

        if risk == RiskLevel.LOW:
            request.status = "approved"
            self._history.append(request)
            logger.debug("LOW risk: %s — auto-approved", tool_name)
            return True

        if risk == RiskLevel.MEDIUM:
            request.status = "approved"
            self._history.append(request)
            logger.info("MEDIUM risk: %s — auto-approved with notice", tool_name)
            return True

        # HIGH risk — need approval
        logger.warning("HIGH risk: %s — awaiting approval", tool_name)

        if not self._callback:
            logger.error("No approval callback configured — rejecting HIGH risk action: %s", tool_name)
            request.status = "rejected"
            self._history.append(request)
            return False

        try:
            result = await asyncio.wait_for(
                self._callback(request),
                timeout=self._timeout,
            )
            # Validate callback returned a bool
            if not isinstance(result, bool):
                logger.error("Approval callback returned non-bool: %s — treating as rejected", type(result))
                result = False
            request.status = "approved" if result else "rejected"
            self._history.append(request)
            logger.info("Approval %s for %s", request.status, tool_name)
            return result
        except asyncio.TimeoutError:
            request.status = "timeout"
            self._history.append(request)
            logger.warning("Approval timeout for %s after %ds", tool_name, self._timeout)
            return False
        except Exception as e:
            logger.error("Approval callback error for %s: %s", tool_name, e)
            request.status = "rejected"
            self._history.append(request)
            return False

    def get_history(self, session_id: Optional[str] = None) -> list[dict]:
        """Get approval history, optionally filtered by session."""
        history = list(self._history)
        if session_id:
            history = [r for r in history if r.session_id == session_id]
        return [r.to_dict() for r in history]

    @property
    def history_size(self) -> int:
        return len(self._history)
