"""SecureAgent SDK — Event Ingest API.

Receives batched audit events from SecureAgent SDK clients and persists them
to the database with tenant isolation.
"""

import logging
import re
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.api_keys import validate_api_key
from api.services.audit_storage import save_audit_events
from db.database import get_db
from db.models import ApiKey
from security.merkle_audit import audit_chain

logger = logging.getLogger("agentos.api.ingest")

router = APIRouter(prefix="/api/v1", tags=["ingest"])

_TOOL_NAME_RE = re.compile(r'^[a-zA-Z0-9_.\-]{0,100}$')


# ─── Models ─────────────────────────────────────────────────────────────

class IngestEvent(BaseModel):
    """A single event from the SDK."""
    type: str = Field(..., min_length=1, max_length=64, description="Event type")
    tool_name: str = Field(default="", max_length=100)
    session_id: str = Field(default="", max_length=128)
    agent_id: str = Field(default="default", max_length=100)
    risk_level: str = Field(default="low", max_length=16)
    model_used: str = Field(default="", max_length=128)
    tokens_used: int = Field(default=0, ge=0, le=10_000_000)
    cost: float = Field(default=0.0, ge=0.0, le=100_000.0)
    input_data: str = Field(default="", max_length=10_000)
    output_data: str = Field(default="", max_length=10_000)
    metadata: dict = Field(default_factory=dict)

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        if v and not _TOOL_NAME_RE.match(v):
            raise ValueError("tool_name must match [a-zA-Z0-9_.\\-]{0,100}")
        return v

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str) -> str:
        if v not in ("low", "medium", "high"):
            return "low"
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict) -> dict:
        import json
        serialized = json.dumps(v, default=str)
        if len(serialized) > 5120:  # 5KB max
            return {"_truncated": True, "_size": len(serialized)}
        return v


class IngestBatch(BaseModel):
    """Batch of events from the SDK."""
    events: list[IngestEvent] = Field(..., min_length=1, max_length=100)


class IngestResponse(BaseModel):
    """Response after successful ingestion."""
    accepted: int
    batch_id: str


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

    if not api_key.permissions.get("ingest", False):
        raise HTTPException(status_code=403, detail="API key does not have ingest permission")

    return api_key


# ─── Routes ─────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
async def ingest_events(
    batch: IngestBatch,
    api_key: ApiKey = Depends(get_authenticated_key),
    db: AsyncSession = Depends(get_db),
):
    """Receive a batch of audit events from an SDK client.

    Events are persisted to the database with tenant isolation and also
    fed into the in-memory merkle audit chain.
    """
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    tenant_id = api_key.tenant_id

    # Prepare events for DB storage
    db_events = []
    for event in batch.events:
        session_id = event.session_id or f"sess_{uuid.uuid4().hex[:8]}"

        event_data = {
            "event_id": f"evt_{session_id}_{uuid.uuid4().hex[:8]}",
            "session_id": session_id,
            "agent_id": event.agent_id,
            "action": event.type,
            "tool_name": event.tool_name,
            "input_hash": event.input_data,
            "output_hash": event.output_data,
            "model_used": event.model_used,
            "tokens_used": event.tokens_used,
            "cost": event.cost,
            "risk_level": event.risk_level,
            "metadata": {
                "batch_id": batch_id,
                "source": "sdk",
                **event.metadata,
            },
        }
        db_events.append(event_data)

        # Also add to in-memory audit chain for real-time queries
        try:
            audit_chain.add_event(
                task_id=session_id,
                agent_id=event.agent_id,
                action=event.type,
                input_data=event.input_data,
                output_data=event.output_data,
                model_used=event.model_used,
                tokens_used=event.tokens_used,
                cost=event.cost,
                metadata=event_data["metadata"],
            )
        except Exception as e:
            logger.error("Failed to add to in-memory audit chain: %s", e)

    # Persist to database
    accepted = await save_audit_events(db, db_events, tenant_id, batch_id)

    logger.info(
        "Ingested %d/%d events (batch=%s, tenant=%s)",
        accepted, len(batch.events), batch_id, tenant_id,
    )
    return IngestResponse(accepted=accepted, batch_id=batch_id)


@router.get("/health/ingest")
async def ingest_health():
    """Health check for the ingest endpoint."""
    return {"status": "ok", "service": "ingest"}
