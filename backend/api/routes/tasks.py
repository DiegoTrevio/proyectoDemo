"""Task management endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import ErrorResponse, TaskCreate, TaskListResponse, TaskResponse
from config.model_router import select_model
from db.database import get_db
from db.models import Task

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

# Rough cost estimation per 1K tokens by model tier
_COST_PER_1K: dict[str, float] = {
    "agentOS/orchestrator": 0.015,
    "agentOS/workhorse": 0.003,
    "agentOS/workhorse-gemini": 0.0005,
    "agentOS/workhorse-qwen": 0.0004,
    "agentOS/workhorse-kimi": 0.0004,
    "agentOS/cheap": 0.0001,
    "agentOS/cheap-qwen": 0.00008,
    "agentOS/facts": 0.005,
}


def _estimate_cost(goal: str, model: str) -> float:
    est_tokens = max(len(goal.split()) * 4, 200)
    rate = _COST_PER_1K.get(model, 0.003)
    return round(rate * est_tokens / 1000, 6)


def _task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        task_id=task.id,
        goal=task.goal,
        status=task.status,
        estimated_cost=task.estimated_cost,
        model=task.model,
        result=task.result,
        artifacts=task.artifacts,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    """Create a new task and queue it for execution."""
    if body.model_preference:
        model = body.model_preference
    else:
        selection = select_model("code", "medium")
        model = selection.model

    estimated_cost = _estimate_cost(body.goal, model)

    task = Task(
        id=uuid.uuid4().hex,
        goal=body.goal,
        status="queued",
        model=model,
        config=body.config,
        estimated_cost=estimated_cost,
        budget_limit=body.budget_limit,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_to_response(task)


@router.get("/{task_id}", response_model=TaskResponse, responses={404: {"model": ErrorResponse}})
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Get task status and artifacts."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_response(task)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List tasks with pagination."""
    offset = (page - 1) * page_size
    total_result = await db.execute(select(func.count(Task.id)))
    total = total_result.scalar_one()

    result = await db.execute(
        select(Task).order_by(Task.created_at.desc()).offset(offset).limit(page_size)
    )
    tasks = result.scalars().all()
    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/{task_id}", responses={404: {"model": ErrorResponse}})
async def cancel_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a queued or running task."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Task already {task.status}")
    task.status = "cancelled"
    task.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"task_id": task_id, "status": "cancelled"}
