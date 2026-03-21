"""SecureAgent SDK — Event Ingest API.

Receives batched audit events from SecureAgent SDK clients and stores them
in the database + merkle audit chain for dashboard visualization.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from security.merkle_audit import audit_chain

logger = logging.getLogger("agentos.api.ingest")

router = APIRouter(prefix="/api/v1", tags=["ingest"])


# ─── Models ─────────────────────────────────────────────────────────────

class IngestEvent(BaseModel):
    """A single event from the SDK."""
    type: str = Field(..., description="Event type: tool_call, pii_detected, taint_violation, etc.")
    tool_name: str = Field(default="", description="Tool that was called")
    session_id: str = Field(default="", description="SDK session identifier")
    agent_id: str = Field(default="default", description="Agent identifier")
    risk_level: str = Field(default="low", description="Risk level: low, medium, high")
    model_used: str = Field(default="", description="LLM model used")
    tokens_used: int = Field(default=0, description="Tokens consumed")
    cost: float = Field(default=0.0, description="Cost in USD")
    input_data: str = Field(default="", description="Hashed or truncated input")
    output_data: str = Field(default="", description="Hashed or truncated output")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    _ts: Optional[float] = None


class IngestBatch(BaseModel):
    """Batch of events from the SDK."""
    events: list[IngestEvent] = Field(..., min_length=1, max_length=500)


class IngestResponse(BaseModel):
    """Response after successful ingestion."""
    accepted: int
    batch_id: str


# ─── Auth helper ────────────────────────────────────────────────────────

async def verify_api_key(authorization: str = Header(...)) -> str:
    """Extract and verify API key from Authorization header.

    In production, this would validate against the database.
    For now, accepts any Bearer token as the tenant identifier.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    api_key = authorization[7:]
    if not api_key or len(api_key) < 8:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # TODO: Look up tenant from API key in database
    return api_key


# ─── Routes ─────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
async def ingest_events(
    batch: IngestBatch,
    api_key: str = Depends(verify_api_key),
):
    """Receive a batch of audit events from an SDK client.

    Events are stored in the merkle audit chain and will be visible
    in the dashboard.
    """
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    accepted = 0

    for event in batch.events:
        try:
            session_id = event.session_id or f"sdk_{api_key[:8]}"

            audit_chain.add_event(
                task_id=session_id,
                agent_id=event.agent_id,
                action=event.type,
                input_data=event.input_data,
                output_data=event.output_data,
                model_used=event.model_used,
                tokens_used=event.tokens_used,
                cost=event.cost,
                metadata={
                    "tool_name": event.tool_name,
                    "risk_level": event.risk_level,
                    "batch_id": batch_id,
                    "source": "sdk",
                    **event.metadata,
                },
            )
            accepted += 1
        except Exception as e:
            logger.error("Failed to ingest event: %s", e)

    logger.info("Ingested %d/%d events (batch=%s)", accepted, len(batch.events), batch_id)
    return IngestResponse(accepted=accepted, batch_id=batch_id)


@router.get("/health/ingest")
async def ingest_health():
    """Health check for the ingest endpoint."""
    return {"status": "ok", "service": "ingest"}
