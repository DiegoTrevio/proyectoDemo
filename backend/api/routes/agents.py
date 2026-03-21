"""Agent management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import AuthUser, require_auth
from api.schemas import AgentCreate, AgentResponse
from db.database import get_db
from db.models import Agent

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

# Core agents shipped with AgentOS
CORE_AGENTS = [
    {"name": "orchestrator", "type": "core", "tools": ["delegate", "plan", "route"], "model": "agentOS/orchestrator"},
    {"name": "researcher", "type": "core", "tools": ["web_search", "scrape", "summarize"], "model": "agentOS/workhorse-gemini"},
    {"name": "coder", "type": "core", "tools": ["code_edit", "terminal", "file_read"], "model": "agentOS/workhorse"},
    {"name": "browser", "type": "core", "tools": ["navigate", "click", "screenshot", "extract"], "model": "agentOS/workhorse-kimi"},
    {"name": "document_writer", "type": "core", "tools": ["write_doc", "format", "export"], "model": "agentOS/workhorse-qwen"},
    {"name": "validator", "type": "core", "tools": ["lint", "test", "review"], "model": "agentOS/cheap"},
]


@router.get("", response_model=list[AgentResponse])
async def list_agents(user: AuthUser = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """List all available agents (core + custom)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    core = [
        AgentResponse(
            agent_id=f"core-{a['name']}",
            name=a["name"],
            type="core",
            tools=a["tools"],
            model=a["model"],
            created_at=now,
        )
        for a in CORE_AGENTS
    ]

    result = await db.execute(select(Agent).where(Agent.is_core == False))  # noqa: E712
    custom = [
        AgentResponse(
            agent_id=a.id,
            name=a.name,
            type=a.type,
            system_prompt=a.system_prompt,
            tools=a.tools or [],
            model=a.model,
            created_at=a.created_at,
        )
        for a in result.scalars().all()
    ]

    return core + custom


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(body: AgentCreate, user: AuthUser = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Create a custom agent."""
    existing = await db.execute(select(Agent).where(Agent.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists")

    agent = Agent(
        id=uuid.uuid4().hex,
        name=body.name,
        type="custom",
        system_prompt=body.system_prompt,
        tools=body.tools,
        model=body.model or "agentOS/workhorse",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    return AgentResponse(
        agent_id=agent.id,
        name=agent.name,
        type=agent.type,
        system_prompt=agent.system_prompt,
        tools=agent.tools or [],
        model=agent.model,
        created_at=agent.created_at,
    )
