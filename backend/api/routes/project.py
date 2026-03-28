"""Project Context endpoints — structured project-level memory with drift detection."""

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    ProjectDriftResponse,
    ProjectScaffoldResponse,
    ProjectSectionResponse,
    ProjectSectionStore,
)
from memory.project_context import SECTION_TYPES, ProjectContext, project_context

router = APIRouter(prefix="/api/v1/project", tags=["project-context"])


@router.post("/sections", response_model=ProjectSectionResponse, status_code=201)
async def store_section(body: ProjectSectionStore):
    """Store or update a project context section."""
    project_context.store_section(body.section, body.content, body.metadata)
    return ProjectSectionResponse(
        section=body.section,
        content=body.content,
        metadata=body.metadata or {},
    )


@router.get("/sections/{section}", response_model=ProjectSectionResponse)
async def get_section(section: str, tier: int = Query(2, ge=0, le=2)):
    """Retrieve a project context section at a specific tier."""
    if section not in SECTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid section. Must be one of {SECTION_TYPES}")

    content = project_context.get_section(section, tier=tier)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Section '{section}' not found")

    entry = project_context._path(section)
    from memory.openviking_layer import openviking
    ov_entry = openviking._fallback_store.get(entry)
    metadata = ov_entry.metadata if ov_entry else {}

    return ProjectSectionResponse(section=section, content=content, metadata=metadata)


@router.get("/sections", response_model=list[ProjectSectionResponse])
async def list_sections(tier: int = Query(0, ge=0, le=2)):
    """List all populated project context sections."""
    sections = project_context.get_all_sections(tier=tier)
    results = []
    for name, content in sections.items():
        from memory.openviking_layer import openviking
        ov_entry = openviking._fallback_store.get(project_context._path(name))
        results.append(ProjectSectionResponse(
            section=name,
            content=content,
            metadata=ov_entry.metadata if ov_entry else {},
        ))
    return results


@router.delete("/sections/{section}")
async def delete_section(section: str):
    """Delete a project context section."""
    if section not in SECTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid section. Must be one of {SECTION_TYPES}")
    if not project_context.delete_section(section):
        raise HTTPException(status_code=404, detail=f"Section '{section}' not found")
    return {"status": "deleted", "section": section}


@router.get("/drift", response_model=ProjectDriftResponse)
async def check_drift():
    """Run drift detection and return a health report."""
    report = project_context.check_drift()
    return ProjectDriftResponse(
        score=report.score,
        healthy=report.healthy,
        issues=[
            {
                "severity": i.severity,
                "code": i.code,
                "message": i.message,
                "section": i.section,
                "detail": i.detail,
            }
            for i in report.issues
        ],
        checked_at=report.checked_at,
    )


@router.get("/scaffold", response_model=ProjectScaffoldResponse)
async def export_scaffold():
    """Export the full project context scaffold (all sections + drift report)."""
    scaffold = project_context.export_scaffold()
    return ProjectScaffoldResponse(**scaffold)


@router.post("/populate")
async def populate_sections(analysis: dict[str, str]):
    """Bulk-populate project context from a project analysis dict."""
    paths = project_context.populate_from_analysis(analysis)
    return {"status": "populated", "sections_stored": len(paths), "paths": paths}


@router.get("/route")
async def route_task(goal: str = Query(..., min_length=1)):
    """Preview which sections would be loaded for a given task goal."""
    sections = project_context.route_for_task(goal)
    context = project_context.get_context_for_task(goal)
    return {
        "goal": goal,
        "routed_sections": sections,
        "context_preview": context[:500] if context else "",
        "context_tokens_estimate": len(context) // 4 if context else 0,
    }
