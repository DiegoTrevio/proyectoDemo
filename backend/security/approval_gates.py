"""Approval Gates — blocks irreversible actions until human approval.

Actions classified as HIGH risk are blocked until explicit approval arrives
via WebSocket or times out after 5 minutes.
"""

import asyncio
import functools
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import redis.asyncio as aioredis

from config.settings import settings

logger = logging.getLogger("agentos.security.approval")

APPROVAL_TIMEOUT = 300  # 5 minutes


class RiskLevel(str, Enum):
    LOW = "low"       # Log only
    MEDIUM = "medium"  # Notify user via SSE
    HIGH = "high"      # Block execution until approval


@dataclass
class ApprovalRequest:
    """Represents a pending approval."""
    id: str
    task_id: str
    action: str
    reason: str
    risk_level: RiskLevel
    params: dict = field(default_factory=dict)
    created_at: str = ""
    status: str = "pending"  # pending, approved, rejected, timeout
    decided_by: str = ""
    decided_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


# ── Pending approvals store ──────────────────────────────────────────────

_pending: dict[str, asyncio.Future] = {}


async def _publish_approval_event(request: ApprovalRequest) -> None:
    """Send approval_required event via SSE to the frontend."""
    r = aioredis.from_url(settings.redis_url)
    try:
        payload = json.dumps({
            "type": "approval_required",
            "action": request.action,
            "reason": request.reason,
            "risk_level": request.risk_level.value,
            "approval_id": request.id,
            "params": request.params,
            "timestamp": request.created_at,
        })
        await r.publish(f"task:{request.task_id}:events", payload)
    finally:
        await r.close()


async def request_approval(
    task_id: str,
    action: str,
    reason: str,
    risk_level: RiskLevel,
    params: dict | None = None,
) -> bool:
    """Request human approval for an action.

    For LOW risk: logs and returns True immediately.
    For MEDIUM risk: notifies via SSE and returns True immediately.
    For HIGH risk: blocks until approval or timeout (5 min).

    Returns True if approved, False if rejected/timeout.
    """
    import uuid
    approval_id = str(uuid.uuid4())[:8]

    req = ApprovalRequest(
        id=approval_id,
        task_id=task_id,
        action=action,
        reason=reason,
        risk_level=risk_level,
        params=params or {},
    )

    if risk_level == RiskLevel.LOW:
        logger.info("LOW risk action logged: %s — %s", action, reason)
        return True

    if risk_level == RiskLevel.MEDIUM:
        logger.info("MEDIUM risk action notified: %s — %s", action, reason)
        await _publish_approval_event(req)
        return True

    # HIGH risk — block until approval
    logger.warning("HIGH risk action requires approval: %s — %s", action, reason)
    await _publish_approval_event(req)

    # Create future that will be resolved by handle_approval_response
    loop = asyncio.get_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    _pending[approval_id] = future

    # Also store in Redis for WebSocket handler to find
    r = aioredis.from_url(settings.redis_url)
    try:
        await r.set(
            f"approval:{approval_id}",
            json.dumps({"task_id": task_id, "action": action, "status": "pending"}),
            ex=APPROVAL_TIMEOUT + 60,
        )
    finally:
        await r.close()

    try:
        result = await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT)
        logger.info("Approval %s: %s for %s", "granted" if result else "rejected", approval_id, action)
        return result
    except asyncio.TimeoutError:
        logger.warning("Approval timeout for %s: %s", approval_id, action)
        _pending.pop(approval_id, None)
        return False


async def handle_approval_response(approval_id: str, approved: bool, user_id: str = "") -> bool:
    """Handle approval response from WebSocket/API.

    Called when the user clicks approve/reject in the frontend.
    Returns True if the approval was found and resolved.
    """
    future = _pending.pop(approval_id, None)

    if future and not future.done():
        future.set_result(approved)
        logger.info("Approval %s resolved: %s by %s", approval_id, approved, user_id)

        # Update Redis
        r = aioredis.from_url(settings.redis_url)
        try:
            await r.set(
                f"approval:{approval_id}",
                json.dumps({
                    "status": "approved" if approved else "rejected",
                    "decided_by": user_id,
                    "decided_at": datetime.now(timezone.utc).isoformat(),
                }),
                ex=3600,
            )
        finally:
            await r.close()

        return True

    logger.warning("Approval %s not found or already resolved", approval_id)
    return False


# ── Decorator ────────────────────────────────────────────────────────────

def requires_approval(reason: str, risk_level: str = "HIGH"):
    """Decorator that gates function execution behind approval.

    Usage:
        @requires_approval("Sending email via Gmail", "HIGH")
        async def send_email(task_id, to, subject, body):
            ...
    """
    level = RiskLevel(risk_level.lower())

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract task_id from args or kwargs
            task_id = kwargs.get("task_id", "")
            if not task_id and args:
                task_id = str(args[0]) if args else "unknown"

            params = {k: str(v)[:200] for k, v in kwargs.items() if k != "task_id"}

            approved = await request_approval(
                task_id=task_id,
                action=func.__name__,
                reason=reason,
                risk_level=level,
                params=params,
            )

            if not approved:
                raise PermissionError(
                    f"Action '{func.__name__}' rejected: {reason} "
                    f"(risk_level={level.value})"
                )

            return await func(*args, **kwargs)

        wrapper._requires_approval = True
        wrapper._risk_level = level
        wrapper._approval_reason = reason
        return wrapper

    return decorator


# ── HIGH-risk action registry ────────────────────────────────────────────

HIGH_RISK_ACTIONS = {
    "send_email": "Sending email via Gmail",
    "make_payment": "Processing payment via Stripe",
    "delete_file": "Deleting file or data",
    "delete_data": "Deleting data from database",
    "publish_content": "Publishing content to social media",
    "push_code": "Pushing code to repository",
    "create_pr": "Creating pull request",
    "update_crm": "Modifying CRM data",
    "send_message": "Sending message via Slack/chat",
    "drop_table": "Dropping database table",
    "code_execute": "Executing arbitrary code in sandbox",
}


def is_high_risk(action: str) -> bool:
    """Check if an action requires HIGH approval."""
    return action in HIGH_RISK_ACTIONS
