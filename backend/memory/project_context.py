"""Project Context — structured project-level memory inspired by mex.

Stores and retrieves project knowledge organized into sections:
  - architecture: system design, components, data flow
  - stack: languages, frameworks, dependencies, versions
  - conventions: coding standards, naming, patterns
  - decisions: ADRs (architecture decision records)
  - setup: environment, build, deploy instructions

Each section is stored in OpenViking with L0/L1/L2 tiers for token-efficient
retrieval.  A routing table maps task keywords to relevant sections so the
orchestrator can load only what's needed.

Drift detection validates that stored context hasn't gone stale by checking
timestamps, referenced paths, and dependency versions.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from memory.openviking_layer import openviking

logger = logging.getLogger("agentos.memory.project_context")

SECTION_TYPES = ("architecture", "stack", "conventions", "decisions", "setup")
SectionType = Literal["architecture", "stack", "conventions", "decisions", "setup"]

_VIKING_PREFIX = "viking://project/"

# ── Routing table: keywords → relevant sections ─────────────────────────────
_ROUTING_TABLE: dict[str, list[SectionType]] = {
    # Architecture
    "design": ["architecture"],
    "component": ["architecture"],
    "diagram": ["architecture"],
    "system": ["architecture"],
    "data flow": ["architecture"],
    "microservice": ["architecture"],
    "module": ["architecture"],
    # Stack
    "dependency": ["stack"],
    "framework": ["stack"],
    "library": ["stack"],
    "version": ["stack"],
    "upgrade": ["stack"],
    "package": ["stack"],
    "language": ["stack"],
    # Conventions
    "naming": ["conventions"],
    "style": ["conventions"],
    "lint": ["conventions"],
    "format": ["conventions"],
    "pattern": ["conventions"],
    "convention": ["conventions"],
    "standard": ["conventions"],
    # Decisions
    "decision": ["decisions"],
    "adr": ["decisions"],
    "why": ["decisions"],
    "trade-off": ["decisions"],
    "alternative": ["decisions"],
    # Setup
    "setup": ["setup"],
    "install": ["setup"],
    "deploy": ["setup"],
    "environment": ["setup"],
    "docker": ["setup"],
    "build": ["setup"],
    "ci": ["setup"],
    # Multi-section
    "refactor": ["architecture", "conventions"],
    "migrate": ["stack", "architecture", "decisions"],
    "new feature": ["architecture", "conventions", "stack"],
    "bug": ["conventions", "architecture"],
    "test": ["conventions", "setup"],
}


@dataclass
class DriftIssue:
    """A single drift detection finding."""

    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    section: str
    detail: str = ""

    @property
    def penalty(self) -> int:
        return {"error": 10, "warning": 3, "info": 1}[self.severity]


@dataclass
class DriftReport:
    """Aggregated drift report."""

    score: int  # 0-100, starts at 100
    issues: list[DriftIssue] = field(default_factory=list)
    checked_at: str = ""

    @property
    def healthy(self) -> bool:
        return self.score >= 70


@dataclass
class ProjectSection:
    """A single project context section."""

    section_type: SectionType
    content: str
    metadata: dict = field(default_factory=dict)
    updated_at: str = ""


class ProjectContext:
    """Manages structured project-level context stored in OpenViking.

    Provides:
      - Section CRUD (architecture, stack, conventions, decisions, setup)
      - Task-based routing: given a goal, returns only relevant sections
      - Drift detection: validates stored context for staleness and broken refs
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id

    def _path(self, section: SectionType) -> str:
        return f"{_VIKING_PREFIX}{self.project_id}/{section}"

    # ── CRUD ──────────────────────────────────────────────────────────────

    def store_section(
        self,
        section: SectionType,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """Store or update a project context section."""
        if section not in SECTION_TYPES:
            raise ValueError(f"Invalid section: {section}. Must be one of {SECTION_TYPES}")

        now = datetime.now(timezone.utc).isoformat()
        meta = metadata or {}
        meta["section_type"] = section
        meta["project_id"] = self.project_id
        meta["updated_at"] = now

        path = openviking.store(
            path=self._path(section),
            content=content,
            metadata=meta,
        )
        logger.info("Stored project context [%s/%s] (%d chars)", self.project_id, section, len(content))
        return path

    def get_section(self, section: SectionType, tier: int = 2) -> str | None:
        """Retrieve a project context section at the specified tier."""
        return openviking.retrieve(self._path(section), tier=tier)

    def get_all_sections(self, tier: int = 0) -> dict[str, str]:
        """Retrieve all sections at the specified tier."""
        result = {}
        for section in SECTION_TYPES:
            content = openviking.retrieve(self._path(section), tier=tier)
            if content:
                result[section] = content
        return result

    def delete_section(self, section: SectionType) -> bool:
        """Delete a project context section."""
        return openviking.delete(self._path(section))

    # ── Routing ───────────────────────────────────────────────────────────

    def route_for_task(self, goal: str) -> list[SectionType]:
        """Determine which sections are relevant for a given task goal.

        Uses keyword matching against the routing table.  Returns a
        deduplicated list of section types, most relevant first.
        """
        goal_lower = goal.lower()
        scored: dict[SectionType, float] = {}

        for keyword, sections in _ROUTING_TABLE.items():
            if keyword in goal_lower:
                for s in sections:
                    scored[s] = scored.get(s, 0) + 1.0

        if not scored:
            # Default: return architecture + conventions (most commonly useful)
            return ["architecture", "conventions"]

        return sorted(scored, key=scored.get, reverse=True)

    def get_context_for_task(self, goal: str, max_tokens: int = 500) -> str:
        """Build token-budgeted context from relevant project sections.

        Routes the task goal to relevant sections, then assembles context
        starting with L0 summaries, escalating to L1 if budget allows.
        """
        sections = self.route_for_task(goal)
        parts = []
        budget = max_tokens

        for section in sections:
            # Start with L0 (cheapest)
            content = self.get_section(section, tier=0)
            if not content:
                continue

            est_tokens = len(content) // 4
            if est_tokens > budget:
                continue

            parts.append(f"[Project/{section}]\n{content}")
            budget -= est_tokens

        # If budget remains, upgrade top section to L1
        if budget > 200 and sections:
            l1 = self.get_section(sections[0], tier=1)
            if l1 and len(l1) // 4 <= budget + len(parts[0]) // 4 if parts else 0:
                if parts:
                    parts[0] = f"[Project/{sections[0]}]\n{l1}"

        return "\n\n".join(parts) if parts else ""

    # ── Drift Detection ───────────────────────────────────────────────────

    def check_drift(self) -> DriftReport:
        """Run drift detection across all project context sections.

        Checks:
          1. Staleness — sections not updated in >30 days
          2. Empty sections — stored but with no content
          3. Broken file references — paths mentioned in content that look
             like file paths (e.g. src/foo.py) but stored context may be stale
          4. Version references — detects version strings that may need updating
          5. Coverage — checks if key sections are populated

        Returns a DriftReport with score (100 = perfect, 0 = fully drifted).
        """
        issues: list[DriftIssue] = []
        now = datetime.now(timezone.utc)

        populated_sections = set()

        for section in SECTION_TYPES:
            entry = openviking._fallback_store.get(self._path(section))

            # ── Coverage check ──
            if entry is None:
                issues.append(DriftIssue(
                    severity="warning",
                    code="MISSING_SECTION",
                    message=f"Section '{section}' is not populated",
                    section=section,
                ))
                continue

            populated_sections.add(section)

            # ── Empty check ──
            if not entry.l2.strip():
                issues.append(DriftIssue(
                    severity="error",
                    code="EMPTY_SECTION",
                    message=f"Section '{section}' is stored but empty",
                    section=section,
                ))
                continue

            # ── Staleness check ──
            updated_at = entry.metadata.get("updated_at", entry.updated_at)
            if updated_at:
                try:
                    last_update = datetime.fromisoformat(updated_at)
                    if last_update.tzinfo is None:
                        last_update = last_update.replace(tzinfo=timezone.utc)
                    age_days = (now - last_update).days
                    if age_days > 30:
                        issues.append(DriftIssue(
                            severity="warning",
                            code="STALE_SECTION",
                            message=f"Section '{section}' last updated {age_days} days ago",
                            section=section,
                            detail=f"Updated: {updated_at}",
                        ))
                except (ValueError, TypeError):
                    pass

            # ── Version reference check ──
            version_pattern = re.compile(r'["\']?\d+\.\d+\.\d+["\']?')
            versions = version_pattern.findall(entry.l2)
            if len(versions) > 5:
                issues.append(DriftIssue(
                    severity="info",
                    code="MANY_VERSIONS",
                    message=f"Section '{section}' references {len(versions)} version strings",
                    section=section,
                    detail="Consider verifying versions are current",
                ))

            # ── File path reference check ──
            path_pattern = re.compile(r'(?:^|\s)((?:src|lib|app|backend|frontend|config|test|tests)/[\w/.-]+\.[\w]+)', re.MULTILINE)
            paths = path_pattern.findall(entry.l2)
            if paths:
                # Store the count as info — actual file validation would need filesystem access
                issues.append(DriftIssue(
                    severity="info",
                    code="FILE_REFERENCES",
                    message=f"Section '{section}' references {len(paths)} file paths",
                    section=section,
                    detail=f"Paths: {', '.join(paths[:5])}",
                ))

        # ── Coverage score ──
        if len(populated_sections) < 3:
            issues.append(DriftIssue(
                severity="warning",
                code="LOW_COVERAGE",
                message=f"Only {len(populated_sections)}/{len(SECTION_TYPES)} sections populated",
                section="*",
            ))

        # Calculate score
        score = 100
        for issue in issues:
            score -= issue.penalty
        score = max(0, score)

        return DriftReport(
            score=score,
            issues=issues,
            checked_at=now.isoformat(),
        )

    # ── Bulk operations ───────────────────────────────────────────────────

    def populate_from_analysis(self, analysis: dict[str, str]) -> list[str]:
        """Populate multiple sections at once from a project analysis.

        Args:
            analysis: Dict mapping section names to content.
                      e.g. {"architecture": "...", "stack": "..."}

        Returns:
            List of stored paths.
        """
        paths = []
        for section_name, content in analysis.items():
            if section_name in SECTION_TYPES and content.strip():
                path = self.store_section(section_name, content)
                paths.append(path)
        return paths

    def export_scaffold(self) -> dict:
        """Export all project context as a portable dict."""
        scaffold = {
            "project_id": self.project_id,
            "sections": {},
            "drift": None,
        }
        for section in SECTION_TYPES:
            entry = openviking._fallback_store.get(self._path(section))
            if entry:
                scaffold["sections"][section] = {
                    "content": entry.l2,
                    "summary": entry.l0,
                    "metadata": entry.metadata,
                }

        report = self.check_drift()
        scaffold["drift"] = {
            "score": report.score,
            "healthy": report.healthy,
            "issues_count": len(report.issues),
            "checked_at": report.checked_at,
        }
        return scaffold


# Default singleton
project_context = ProjectContext()
