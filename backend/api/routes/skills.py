"""Skills catalog endpoints — list, match, and preview skill instructions."""

from fastapi import APIRouter, Query

from agents.skills.registry import skill_registry

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


@router.get("")
async def list_skills():
    """List all available skills in the catalog."""
    return [
        {
            "name": s.name,
            "description": s.description,
            "version": s.version,
            "agents": s.agents,
            "complexity_hint": s.complexity_hint,
            "tags": s.tags,
            "trigger_count": len(s.triggers),
        }
        for s in skill_registry.list_skills()
    ]


@router.get("/match")
async def match_skills(goal: str = Query(..., min_length=1), task_type: str = ""):
    """Match a goal against the skill catalog and return ranked results."""
    matches = skill_registry.match(goal, task_type, top_k=5)
    return [
        {
            "skill": m.skill.name,
            "confidence": round(m.confidence, 2),
            "matched_triggers": m.matched_triggers,
            "agents": m.skill.agents,
            "description": m.skill.description,
        }
        for m in matches
    ]


@router.get("/{skill_name}")
async def get_skill(skill_name: str):
    """Get full details of a specific skill."""
    skill = skill_registry.get(skill_name)
    if not skill:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return {
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "agents": skill.agents,
        "triggers": skill.triggers,
        "task_types": skill.task_types,
        "instructions": skill.instructions,
        "tools": skill.tools,
        "complexity_hint": skill.complexity_hint,
        "tags": skill.tags,
    }


@router.get("/{skill_name}/instructions")
async def get_skill_instructions(skill_name: str, agent: str = Query("", description="Filter by agent")):
    """Get the instruction text for a specific skill, optionally filtered by agent."""
    skill = skill_registry.get(skill_name)
    if not skill:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    if agent and skill.agents and agent not in skill.agents:
        return {"skill": skill_name, "agent": agent, "compatible": False, "instructions": ""}

    return {
        "skill": skill_name,
        "agent": agent or "any",
        "compatible": True,
        "instructions": skill.instructions,
    }
