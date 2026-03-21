"""SecureAgent — Enterprise security for AI agents.

Usage:
    from secureagent import SecureAgent

    agent = SecureAgent(
        taint_tracking=True,
        pii_detection=True,
        audit_log=True,
        approval_gates={"delete_file": "high", "send_email": "high"},
    )

    # Wrap any tool call with security
    result = await agent.secure_call("search_web", {"query": "test"})

    # Export audit trail for SOC2/GDPR
    trail = agent.export_audit_trail()
"""

from secureagent.core import SecureAgent, SecurityViolation
from secureagent.taint import TaintTracker, TaintLabel, TaintSource, TaintedContent, TaintViolation
from secureagent.audit import AuditLog, AuditEvent, StorageBackend
from secureagent.gates import ApprovalGate, RiskLevel
from secureagent.pii import PIIDetector

__version__ = "0.1.0"
__all__ = [
    "SecureAgent",
    "SecurityViolation",
    "TaintTracker",
    "TaintLabel",
    "TaintSource",
    "TaintedContent",
    "TaintViolation",
    "AuditLog",
    "AuditEvent",
    "StorageBackend",
    "ApprovalGate",
    "RiskLevel",
    "PIIDetector",
]
