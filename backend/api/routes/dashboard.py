"""SecureAgent SDK — Dashboard API.

Provides endpoints for the audit dashboard: event listing, chain verification,
compliance reports, and usage statistics.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from security.merkle_audit import audit_chain

logger = logging.getLogger("agentos.api.dashboard")

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


# ─── Auth ───────────────────────────────────────────────────────────────

async def verify_api_key(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    api_key = authorization[7:]
    if not api_key or len(api_key) < 8:
        raise HTTPException(status_code=401, detail="Invalid API key")
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
    chain_valid: bool
    total_events: int
    high_risk_events: int
    pii_detections: int
    taint_violations: int
    approval_rejections: int
    audit_trail: list[dict]


class UsageStats(BaseModel):
    session_id: str
    total_events: int
    total_tokens: int
    total_cost: float
    agents: list[str]
    first_event: str
    last_event: str


# ─── Routes ─────────────────────────────────────────────────────────────

@router.get("/events")
async def list_events(
    session_id: str = Query(..., description="Session ID to query"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(100, ge=1, le=1000),
    api_key: str = Depends(verify_api_key),
):
    """List audit events for a session with optional filters."""
    chain = audit_chain._chains.get(session_id, [])

    events = []
    for event in chain:
        if agent_id and event.agent_id != agent_id:
            continue
        if action and event.action != action:
            continue
        events.append({
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "agent_id": event.agent_id,
            "action": event.action,
            "tool_name": event.metadata.get("tool_name", ""),
            "risk_level": event.metadata.get("risk_level", "low"),
            "model_used": event.model_used,
            "tokens_used": event.tokens_used,
            "cost": event.cost,
            "event_hash": event.event_hash[:16],
        })
        if len(events) >= limit:
            break

    return {"session_id": session_id, "events": events, "total": len(events)}


@router.get("/verify", response_model=ChainVerification)
async def verify_chain(
    session_id: str = Query(..., description="Session ID to verify"),
    api_key: str = Depends(verify_api_key),
):
    """Verify integrity of the audit chain for a session."""
    valid, message = audit_chain.verify_chain(session_id)
    chain = audit_chain._chains.get(session_id, [])
    return ChainVerification(
        session_id=session_id,
        valid=valid,
        message=message,
        events=len(chain),
    )


@router.get("/audit/export")
async def export_audit(
    session_id: str = Query(..., description="Session ID to export"),
    api_key: str = Depends(verify_api_key),
):
    """Export full audit trail for SOC2/GDPR compliance."""
    trail = audit_chain.export_chain(session_id)
    valid, message = audit_chain.verify_chain(session_id)

    return {
        "session_id": session_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "chain_valid": valid,
        "chain_message": message,
        "total_events": len(trail),
        "events": trail,
    }


@router.get("/compliance/report", response_model=ComplianceReport)
async def compliance_report(
    session_id: str = Query(..., description="Session ID for the report"),
    api_key: str = Depends(verify_api_key),
):
    """Generate a compliance report for a session."""
    chain = audit_chain._chains.get(session_id, [])
    valid, message = audit_chain.verify_chain(session_id)
    trail = audit_chain.export_chain(session_id)

    high_risk = sum(1 for e in chain if e.metadata.get("risk_level") == "high")
    pii = sum(1 for e in chain if e.action == "pii_detected")
    taint = sum(1 for e in chain if e.action == "taint_violation")
    rejections = sum(1 for e in chain if e.action == "approval_rejected")

    return ComplianceReport(
        session_id=session_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        chain_valid=valid,
        total_events=len(chain),
        high_risk_events=high_risk,
        pii_detections=pii,
        taint_violations=taint,
        approval_rejections=rejections,
        audit_trail=trail,
    )


@router.get("/stats", response_model=UsageStats)
async def usage_stats(
    session_id: str = Query(..., description="Session ID for stats"),
    api_key: str = Depends(verify_api_key),
):
    """Get usage statistics for a session."""
    stats = audit_chain.get_chain_stats(session_id)

    return UsageStats(
        session_id=session_id,
        total_events=stats.get("events", 0),
        total_tokens=stats.get("total_tokens", 0),
        total_cost=stats.get("total_cost", 0.0),
        agents=stats.get("agents", []),
        first_event=stats.get("first_event", ""),
        last_event=stats.get("last_event", ""),
    )


@router.get("/sessions")
async def list_sessions(
    api_key: str = Depends(verify_api_key),
    limit: int = Query(50, ge=1, le=200),
):
    """List all active sessions with summary stats."""
    sessions = []
    for session_id, chain in list(audit_chain._chains.items())[:limit]:
        if not chain:
            continue
        sessions.append({
            "session_id": session_id,
            "events": len(chain),
            "first_event": chain[0].timestamp,
            "last_event": chain[-1].timestamp,
            "agents": list(set(e.agent_id for e in chain)),
        })

    return {"sessions": sessions, "total": len(sessions)}
