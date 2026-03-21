"""SecureAgent SDK — Dashboard API.

Provides tenant-isolated endpoints for the audit dashboard: event listing,
chain verification, compliance reports, and usage statistics.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.api_keys import validate_api_key
from api.services.audit_storage import (
    export_audit_chain,
    get_audit_events,
    get_audit_stats,
    get_sessions,
)
from db.database import get_db
from db.models import ApiKey

logger = logging.getLogger("agentos.api.dashboard")

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


# ─── Auth dependency ────────────────────────────────────────────────────

async def get_authenticated_key(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Validate API key and return the key record with tenant_id."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    raw_key = authorization[7:]
    api_key = await validate_api_key(db, raw_key)

    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    if not api_key.permissions.get("dashboard", False):
        raise HTTPException(status_code=403, detail="API key does not have dashboard permission")

    return api_key


# ─── Models ─────────────────────────────────────────────────────────────

class ChainVerification(BaseModel):
    session_id: str
    valid: bool
    message: str
    events: int


class ComplianceReport(BaseModel):
    session_id: str
    generated_at: str
    total_events: int
    high_risk_events: int
    pii_detections: int
    taint_violations: int
    approval_rejections: int
    audit_trail: list[dict]


class UsageStats(BaseModel):
    total_events: int
    total_tokens: int
    total_cost: float
    first_event: str
    last_event: str


# ─── Routes ─────────────────────────────────────────────────────────────

@router.get("/events")
async def list_events(
    session_id: str = Query(..., max_length=128),
    agent_id: Optional[str] = Query(None, max_length=100),
    action: Optional[str] = Query(None, max_length=64),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    api_key: ApiKey = Depends(get_authenticated_key),
    db: AsyncSession = Depends(get_db),
):
    """List audit events for a session (tenant-isolated)."""
    events = await get_audit_events(
        db,
        tenant_id=api_key.tenant_id,
        session_id=session_id,
        agent_id=agent_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return {"session_id": session_id, "events": events, "total": len(events)}


@router.get("/audit/export")
async def export_audit(
    session_id: str = Query(..., max_length=128),
    api_key: ApiKey = Depends(get_authenticated_key),
    db: AsyncSession = Depends(get_db),
):
    """Export full audit trail for SOC2/GDPR compliance (tenant-isolated)."""
    trail = await export_audit_chain(db, tenant_id=api_key.tenant_id, session_id=session_id)

    return {
        "session_id": session_id,
        "tenant_id": api_key.tenant_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_events": len(trail),
        "events": trail,
    }


@router.get("/compliance/report", response_model=ComplianceReport)
async def compliance_report(
    session_id: str = Query(..., max_length=128),
    api_key: ApiKey = Depends(get_authenticated_key),
    db: AsyncSession = Depends(get_db),
):
    """Generate a compliance report for a session (tenant-isolated)."""
    trail = await export_audit_chain(db, tenant_id=api_key.tenant_id, session_id=session_id)

    high_risk = sum(1 for e in trail if e.get("risk_level") == "high")
    pii = sum(1 for e in trail if e.get("action") == "pii_detected")
    taint = sum(1 for e in trail if e.get("action") == "taint_violation")
    rejections = sum(1 for e in trail if e.get("action") == "approval_rejected")

    return ComplianceReport(
        session_id=session_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_events=len(trail),
        high_risk_events=high_risk,
        pii_detections=pii,
        taint_violations=taint,
        approval_rejections=rejections,
        audit_trail=trail,
    )


@router.get("/stats", response_model=UsageStats)
async def usage_stats(
    session_id: Optional[str] = Query(None, max_length=128),
    api_key: ApiKey = Depends(get_authenticated_key),
    db: AsyncSession = Depends(get_db),
):
    """Get usage statistics (tenant-isolated)."""
    stats = await get_audit_stats(db, tenant_id=api_key.tenant_id, session_id=session_id)

    return UsageStats(
        total_events=stats["total_events"],
        total_tokens=stats["total_tokens"],
        total_cost=stats["total_cost"],
        first_event=stats["first_event"],
        last_event=stats["last_event"],
    )


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    api_key: ApiKey = Depends(get_authenticated_key),
    db: AsyncSession = Depends(get_db),
):
    """List all sessions for the tenant."""
    sessions = await get_sessions(db, tenant_id=api_key.tenant_id, limit=limit)
    return {"sessions": sessions, "total": len(sessions)}
