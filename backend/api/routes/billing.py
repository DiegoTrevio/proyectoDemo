"""Billing estimation and usage endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import AuthUser, require_auth
from api.schemas import BillingEstimate, UsageResponse
from config.model_router import select_model
from db.database import get_db
from db.models import Usage

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

# Cost per 1K tokens (input/output average) by model
_PRICING: dict[str, float] = {
    "agentOS/orchestrator": 0.015,
    "agentOS/workhorse": 0.003,
    "agentOS/workhorse-gemini": 0.0005,
    "agentOS/workhorse-qwen": 0.0004,
    "agentOS/workhorse-kimi": 0.0004,
    "agentOS/cheap": 0.0001,
    "agentOS/cheap-qwen": 0.00008,
    "agentOS/facts": 0.005,
    "agentOS/images": 0.001,
    "agentOS/on-premise": 0.0,
}


@router.get("/estimate", response_model=BillingEstimate)
async def estimate_cost(
    goal: str = Query(..., min_length=1),
    model: str | None = Query(None),
    user: AuthUser = Depends(require_auth),
):
    """Estimate cost BEFORE executing a task."""
    if model:
        chosen_model = model
    else:
        selection = select_model("code", "medium")
        chosen_model = selection.model

    word_count = len(goal.split())
    est_input_tokens = max(word_count * 4, 200) + 500  # goal + system prompt overhead
    est_output_tokens = max(est_input_tokens * 2, 1000)

    rate = _PRICING.get(chosen_model, 0.003)
    total_tokens = est_input_tokens + est_output_tokens
    cost = round(rate * total_tokens / 1000, 6)

    return BillingEstimate(
        model=chosen_model,
        estimated_input_tokens=est_input_tokens,
        estimated_output_tokens=est_output_tokens,
        estimated_cost=cost,
    )


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated usage for the current user."""
    totals = await db.execute(
        select(
            func.coalesce(func.sum(Usage.input_tokens + Usage.output_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(Usage.cost), 0).label("total_cost"),
        )
    )
    row = totals.one()

    # Per-model breakdown
    breakdown_q = await db.execute(
        select(
            Usage.model,
            func.sum(Usage.input_tokens).label("input_tokens"),
            func.sum(Usage.output_tokens).label("output_tokens"),
            func.sum(Usage.cost).label("cost"),
            func.count().label("requests"),
        ).group_by(Usage.model)
    )
    breakdown = [
        {
            "model": r.model,
            "input_tokens": int(r.input_tokens or 0),
            "output_tokens": int(r.output_tokens or 0),
            "cost": float(r.cost or 0),
            "requests": int(r.requests),
        }
        for r in breakdown_q.all()
    ]

    return UsageResponse(
        total_tokens=int(row.total_tokens),
        total_cost=float(row.total_cost),
        breakdown=breakdown,
    )
