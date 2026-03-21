"""Postgres Audit Storage — persists SDK audit events to the database.

Implements batch insert for efficiency and tenant-isolated queries.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditEventDB

logger = logging.getLogger("agentos.services.audit_storage")


async def save_audit_events(
    db: AsyncSession,
    events: list[dict],
    tenant_id: str,
    batch_id: str = "",
) -> int:
    """Batch insert audit events into the database.

    Returns number of events saved.
    """
    saved = 0
    for event_data in events:
        try:
            db_event = AuditEventDB(
                event_id=event_data.get("event_id", ""),
                session_id=event_data.get("session_id", ""),
                tenant_id=tenant_id,
                agent_id=event_data.get("agent_id", "default"),
                action=event_data.get("action", "unknown"),
                tool_name=event_data.get("tool_name", ""),
                input_hash=event_data.get("input_hash", ""),
                output_hash=event_data.get("output_hash", ""),
                model_used=event_data.get("model_used", ""),
                tokens_used=event_data.get("tokens_used", 0),
                cost=event_data.get("cost", 0.0),
                risk_level=event_data.get("risk_level", "low"),
                prev_hash=event_data.get("prev_hash", ""),
                event_hash=event_data.get("event_hash", ""),
                signature=event_data.get("signature", ""),
                metadata=event_data.get("metadata", {}),
                batch_id=batch_id,
            )
            db.add(db_event)
            saved += 1
        except Exception as e:
            logger.error("Failed to create audit event record: %s", e)

    if saved > 0:
        await db.commit()
        logger.debug("Saved %d audit events for tenant %s", saved, tenant_id)

    return saved


async def get_audit_events(
    db: AsyncSession,
    tenant_id: str,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Query audit events with tenant isolation and optional filters."""
    query = select(AuditEventDB).where(AuditEventDB.tenant_id == tenant_id)

    if session_id:
        query = query.where(AuditEventDB.session_id == session_id)
    if agent_id:
        query = query.where(AuditEventDB.agent_id == agent_id)
    if action:
        query = query.where(AuditEventDB.action == action)

    query = query.order_by(AuditEventDB.timestamp.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()

    return [
        {
            "event_id": e.event_id,
            "session_id": e.session_id,
            "timestamp": e.timestamp.isoformat() if e.timestamp else "",
            "agent_id": e.agent_id,
            "action": e.action,
            "tool_name": e.tool_name,
            "risk_level": e.risk_level,
            "model_used": e.model_used,
            "tokens_used": e.tokens_used,
            "cost": e.cost,
            "event_hash": e.event_hash[:16] if e.event_hash else "",
            "metadata": e.metadata,
        }
        for e in events
    ]


async def get_audit_stats(
    db: AsyncSession,
    tenant_id: str,
    session_id: Optional[str] = None,
) -> dict:
    """Get aggregate statistics for audit events."""
    query = select(
        func.count(AuditEventDB.id).label("total_events"),
        func.sum(AuditEventDB.tokens_used).label("total_tokens"),
        func.sum(AuditEventDB.cost).label("total_cost"),
        func.min(AuditEventDB.timestamp).label("first_event"),
        func.max(AuditEventDB.timestamp).label("last_event"),
    ).where(AuditEventDB.tenant_id == tenant_id)

    if session_id:
        query = query.where(AuditEventDB.session_id == session_id)

    result = await db.execute(query)
    row = result.one()

    return {
        "total_events": row.total_events or 0,
        "total_tokens": row.total_tokens or 0,
        "total_cost": float(row.total_cost or 0.0),
        "first_event": row.first_event.isoformat() if row.first_event else "",
        "last_event": row.last_event.isoformat() if row.last_event else "",
    }


async def get_sessions(
    db: AsyncSession,
    tenant_id: str,
    limit: int = 50,
) -> list[dict]:
    """List sessions for a tenant with event counts."""
    query = (
        select(
            AuditEventDB.session_id,
            func.count(AuditEventDB.id).label("event_count"),
            func.min(AuditEventDB.timestamp).label("first_event"),
            func.max(AuditEventDB.timestamp).label("last_event"),
        )
        .where(AuditEventDB.tenant_id == tenant_id)
        .group_by(AuditEventDB.session_id)
        .order_by(func.max(AuditEventDB.timestamp).desc())
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "session_id": row.session_id,
            "events": row.event_count,
            "first_event": row.first_event.isoformat() if row.first_event else "",
            "last_event": row.last_event.isoformat() if row.last_event else "",
        }
        for row in rows
    ]


async def export_audit_chain(
    db: AsyncSession,
    tenant_id: str,
    session_id: str,
) -> list[dict]:
    """Export full audit chain for SOC2/GDPR compliance."""
    query = (
        select(AuditEventDB)
        .where(
            AuditEventDB.tenant_id == tenant_id,
            AuditEventDB.session_id == session_id,
        )
        .order_by(AuditEventDB.timestamp.asc())
    )
    result = await db.execute(query)
    events = result.scalars().all()

    return [
        {
            "event_id": e.event_id,
            "session_id": e.session_id,
            "timestamp": e.timestamp.isoformat() if e.timestamp else "",
            "agent_id": e.agent_id,
            "action": e.action,
            "tool_name": e.tool_name,
            "input_hash": e.input_hash,
            "output_hash": e.output_hash,
            "model_used": e.model_used,
            "tokens_used": e.tokens_used,
            "cost": e.cost,
            "risk_level": e.risk_level,
            "prev_hash": e.prev_hash,
            "event_hash": e.event_hash,
            "signature": e.signature,
            "metadata": e.metadata,
        }
        for e in events
    ]
