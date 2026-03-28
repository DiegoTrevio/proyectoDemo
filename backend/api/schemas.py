"""Pydantic schemas for AgentOS API."""

from datetime import datetime

from pydantic import BaseModel, Field


# ─── Tasks ────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4096)
    config: dict | None = None
    model_preference: str | None = None
    budget_limit: float | None = Field(None, ge=0)


class TaskResponse(BaseModel):
    task_id: str
    goal: str
    status: str
    estimated_cost: float
    model: str | None = None
    result: dict | None = None
    artifacts: list[dict] | None = None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    page: int
    page_size: int


# ─── Stream ───────────────────────────────────────────────────────────────

class StreamEvent(BaseModel):
    type: str = Field(..., pattern=r"^(thought|action|result|error)$")
    content: str
    agent: str
    timestamp: str


# ─── Agents ───────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    system_prompt: str = Field(..., min_length=1, max_length=16384)
    tools: list[str] = Field(default_factory=list)
    model: str | None = None


class AgentResponse(BaseModel):
    agent_id: str
    name: str
    type: str
    system_prompt: str | None = None
    tools: list[str]
    model: str | None = None
    created_at: datetime


# ─── Billing ──────────────────────────────────────────────────────────────

class BillingEstimate(BaseModel):
    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost: float
    currency: str = "USD"


class UsageResponse(BaseModel):
    total_tokens: int
    total_cost: float
    currency: str = "USD"
    breakdown: list[dict]


# ─── Memory ───────────────────────────────────────────────────────────────

class MemoryStoreRequest(BaseModel):
    namespace: str = Field(..., min_length=1, max_length=128)
    key: str = Field(..., min_length=1, max_length=256)
    value: str
    metadata: dict | None = None


class MemoryEntry(BaseModel):
    id: str
    namespace: str
    key: str
    value: str
    metadata: dict
    created_at: str


# ─── Project Context ──────────────────────────────────────────────────────

class ProjectSectionStore(BaseModel):
    section: str = Field(..., pattern=r"^(architecture|stack|conventions|decisions|setup)$")
    content: str = Field(..., min_length=1)
    metadata: dict | None = None


class ProjectSectionResponse(BaseModel):
    section: str
    content: str
    metadata: dict


class ProjectDriftResponse(BaseModel):
    score: int
    healthy: bool
    issues: list[dict]
    checked_at: str


class ProjectScaffoldResponse(BaseModel):
    project_id: str
    sections: dict
    drift: dict


# ─── Generic ──────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: str
