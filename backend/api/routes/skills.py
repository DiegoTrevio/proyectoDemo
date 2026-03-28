"""Skills catalog endpoints — create, list, match, test, and manage skills."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agents.skills.registry import generate_template, skill_registry, validate_skill

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


# ── Schemas ───────────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(..., min_length=1, max_length=512)
    version: str = "1.0"
    agents: list[str] = Field(..., min_length=1)
    triggers: dict = Field(..., description="{'keywords': [...], 'task_types': [...]}")
    instructions: str = Field(..., min_length=50)
    tools: list[str] = Field(default_factory=list)
    complexity_hint: str = "medium"
    tags: list[str] = Field(default_factory=list)


class SkillTest(BaseModel):
    skill: dict = Field(..., description="Skill definition to test (same shape as SkillCreate)")
    sample_goals: list[str] = Field(..., min_length=1, max_length=20)


# ── Endpoints ─────────────────────────────────────────────────────────────

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


@router.post("", status_code=201)
async def create_skill(body: SkillCreate):
    """Create a new skill. Validates, writes SKILL.yaml, and registers immediately.

    The skill is available for matching right away — no restart needed.
    """
    data = body.model_dump()
    try:
        skill, warnings = skill_registry.create_skill(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "status": "created",
        "skill": skill.name,
        "warnings": [{"field": w.field, "message": w.message} for w in warnings],
    }


@router.post("/test")
async def test_skill(body: SkillTest):
    """Dry-run a skill definition against sample goals without registering it.

    Use this to verify triggers work before creating the skill.
    """
    return skill_registry.test_skill(body.skill, body.sample_goals)


@router.post("/validate")
async def validate_skill_endpoint(data: dict):
    """Validate a skill definition without creating it.

    Returns all errors and warnings found.
    """
    issues = validate_skill(data)
    return {
        "valid": not any(e.severity == "error" for e in issues),
        "errors": [{"field": e.field, "message": e.message} for e in issues if e.severity == "error"],
        "warnings": [{"field": e.field, "message": e.message} for e in issues if e.severity == "warning"],
    }


@router.post("/reload")
async def reload_skills():
    """Hot-reload all skills from disk without restarting the server."""
    result = skill_registry.reload()
    return result


@router.get("/template")
async def get_template(name: str = Query("my-skill"), description: str = Query("")):
    """Generate a starter SKILL.yaml template with documentation.

    Copy the output, fill in the fields, and POST to /api/v1/skills to create.
    """
    return {
        "yaml": generate_template(name, description),
        "instructions": "Copy the YAML, fill in the fields, then POST to /api/v1/skills",
    }


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


@router.get("/errors")
async def get_load_errors():
    """Return any validation errors/warnings from the last catalog load."""
    errors = skill_registry.get_load_errors()
    return {
        name: [{"field": e.field, "message": e.message, "severity": e.severity} for e in issues]
        for name, issues in errors.items()
    }


@router.get("/{skill_name}")
async def get_skill(skill_name: str):
    """Get full details of a specific skill."""
    skill = skill_registry.get(skill_name)
    if not skill:
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


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str):
    """Delete a skill from registry and disk."""
    if not skill_registry.delete_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return {"status": "deleted", "skill": skill_name}


@router.get("/{skill_name}/instructions")
async def get_skill_instructions(skill_name: str, agent: str = Query("", description="Filter by agent")):
    """Get the instruction text for a specific skill, optionally filtered by agent."""
    skill = skill_registry.get(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    if agent and skill.agents and agent not in skill.agents:
        return {"skill": skill_name, "agent": agent, "compatible": False, "instructions": ""}

    return {
        "skill": skill_name,
        "agent": agent or "any",
        "compatible": True,
        "instructions": skill.instructions,
    }
