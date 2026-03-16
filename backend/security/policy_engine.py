"""Policy Engine — enforces per-client security policies from PostgreSQL.

Policies control:
  - Allowed/blocked actions per client
  - Blocked topics
  - Actions requiring manual approval
  - Maximum cost per task
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import async_session_factory

logger = logging.getLogger("agentos.security.policy_engine")


@dataclass
class PolicyDecision:
    """Result of a policy check."""
    allowed: bool
    reason: str
    requires_approval: bool = False
    policy_id: str | None = None


@dataclass
class ClientPolicy:
    """A client's security policy."""
    client_id: str
    allowed_actions: list[str] = field(default_factory=list)
    blocked_topics: list[str] = field(default_factory=list)
    require_approval_for: list[str] = field(default_factory=list)
    max_cost_per_task: float = 5.0
    is_active: bool = True

    @classmethod
    def default(cls, client_id: str) -> "ClientPolicy":
        """Return a default permissive policy."""
        return cls(
            client_id=client_id,
            allowed_actions=["*"],
            blocked_topics=[],
            require_approval_for=["delete", "send_email", "make_payment", "deploy"],
            max_cost_per_task=5.0,
        )


# ─── In-memory policy cache ──────────────────────────────────────────────

_policy_cache: dict[str, ClientPolicy] = {}


async def load_policy(client_id: str) -> ClientPolicy:
    """Load a client's policy from PostgreSQL, with caching."""
    if client_id in _policy_cache:
        return _policy_cache[client_id]

    try:
        from db.models import SecurityPolicy

        async with async_session_factory() as session:
            result = await session.execute(
                select(SecurityPolicy).where(
                    SecurityPolicy.client_id == client_id,
                    SecurityPolicy.is_active == True,
                )
            )
            row = result.scalar_one_or_none()

            if row:
                policy = ClientPolicy(
                    client_id=row.client_id,
                    allowed_actions=row.policy_data.get("allowed_actions", ["*"]),
                    blocked_topics=row.policy_data.get("blocked_topics", []),
                    require_approval_for=row.policy_data.get("require_approval_for", []),
                    max_cost_per_task=row.policy_data.get("max_cost_per_task", 5.0),
                    is_active=row.is_active,
                )
            else:
                policy = ClientPolicy.default(client_id)

    except Exception as e:
        logger.warning("Failed to load policy for %s, using default: %s", client_id, e)
        policy = ClientPolicy.default(client_id)

    _policy_cache[client_id] = policy
    return policy


def invalidate_policy_cache(client_id: str | None = None) -> None:
    """Clear policy cache. If client_id is None, clear all."""
    if client_id:
        _policy_cache.pop(client_id, None)
    else:
        _policy_cache.clear()


async def check_policy(
    client_id: str,
    action: str,
    context: dict | None = None,
) -> PolicyDecision:
    """Check whether an action is allowed by the client's policy.

    Args:
        client_id: The client/tenant identifier.
        action: The action being attempted (e.g. "search", "delete", "send_email").
        context: Optional context dict with keys like "topic", "estimated_cost".

    Returns:
        PolicyDecision with allowed status and reason.
    """
    context = context or {}
    policy = await load_policy(client_id)

    if not policy.is_active:
        return PolicyDecision(
            allowed=False,
            reason="Client policy is inactive",
            policy_id=client_id,
        )

    # Check blocked topics
    topic = context.get("topic", "")
    if topic and policy.blocked_topics:
        topic_lower = topic.lower()
        for blocked in policy.blocked_topics:
            if blocked.lower() in topic_lower:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Topic '{blocked}' is blocked by policy",
                    policy_id=client_id,
                )

    # Check allowed actions
    if policy.allowed_actions and "*" not in policy.allowed_actions:
        if action not in policy.allowed_actions:
            return PolicyDecision(
                allowed=False,
                reason=f"Action '{action}' is not in allowed actions list",
                policy_id=client_id,
            )

    # Check cost limit
    estimated_cost = context.get("estimated_cost", 0.0)
    if estimated_cost > policy.max_cost_per_task:
        return PolicyDecision(
            allowed=False,
            reason=f"Estimated cost ${estimated_cost:.2f} exceeds limit ${policy.max_cost_per_task:.2f}",
            policy_id=client_id,
        )

    # Check if approval is required
    requires_approval = action in policy.require_approval_for

    return PolicyDecision(
        allowed=True,
        reason="Policy check passed" if not requires_approval else f"Action '{action}' requires approval",
        requires_approval=requires_approval,
        policy_id=client_id,
    )
