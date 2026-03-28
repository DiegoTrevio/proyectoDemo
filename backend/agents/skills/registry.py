"""Skills Registry — unified skill discovery, matching, and injection.

Skills are domain-specific capabilities that agents can use. Each skill is
defined in a SKILL.yaml file under agents/skills/catalog/ and provides:
  - Trigger keywords for automatic activation
  - Instructions that get injected into the agent's context
  - Agent compatibility (which agents can execute it)
  - Complexity hint for the orchestrator

The registry auto-discovers all SKILL.yaml files at import time and provides
matching functions used by the orchestrator (classify/plan) and dispatcher
(instruction injection).

Creating a new skill:
  1. POST /api/v1/skills with the skill definition (auto-creates SKILL.yaml)
  2. Or manually create catalog/<name>/SKILL.yaml
  3. Call POST /api/v1/skills/reload to pick up changes without restart
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("agentos.skills.registry")

_CATALOG_DIR = Path(__file__).parent / "catalog"

# Known agents in AgentOS (for validation)
_VALID_AGENTS = {"coder", "researcher", "browser", "document_writer", "validator", "deerflow", "hermes"}
_VALID_COMPLEXITY = {"simple", "medium", "complex"}
_VALID_TASK_TYPES = {"code", "research", "browser", "document", "deep_research", "multi"}


@dataclass
class ValidationError:
    """A single validation issue found in a skill definition."""

    field: str
    message: str
    severity: str = "error"  # error or warning


@dataclass
class SkillDefinition:
    """A single skill definition loaded from SKILL.yaml."""

    name: str
    description: str
    version: str = "1.0"
    agents: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    instructions: str = ""
    tools: list[str] = field(default_factory=list)
    complexity_hint: str = "medium"
    tags: list[str] = field(default_factory=list)

    @property
    def trigger_patterns(self) -> list[re.Pattern]:
        """Compile trigger keywords into regex patterns."""
        if not hasattr(self, "_compiled_patterns"):
            self._compiled_patterns = []
            for kw in self.triggers:
                try:
                    self._compiled_patterns.append(re.compile(kw, re.IGNORECASE))
                except re.error:
                    self._compiled_patterns.append(re.compile(re.escape(kw), re.IGNORECASE))
        return self._compiled_patterns

    def to_yaml_dict(self) -> dict:
        """Serialize to a dict suitable for YAML output."""
        d = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "agents": self.agents,
            "triggers": {
                "keywords": self.triggers,
                "task_types": self.task_types,
            },
            "instructions": self.instructions,
            "tools": self.tools,
            "complexity_hint": self.complexity_hint,
            "tags": self.tags,
        }
        return d


@dataclass
class SkillMatch:
    """Result of matching a goal against the skill catalog."""

    skill: SkillDefinition
    confidence: float  # 0.0 to 1.0
    matched_triggers: list[str]


def validate_skill(data: dict) -> list[ValidationError]:
    """Validate a skill definition dict and return any issues found.

    Checks:
      - Required fields present and non-empty
      - Agent names are recognized
      - Trigger regexes compile
      - Complexity hint is valid
      - Task types are recognized
      - Instructions aren't too short
    """
    errors: list[ValidationError] = []

    # Required fields
    if not data.get("name", "").strip():
        errors.append(ValidationError("name", "Required: skill name is missing"))
    elif not re.match(r"^[a-z0-9][a-z0-9-]*$", data["name"]):
        errors.append(ValidationError("name", "Must be lowercase alphanumeric with hyphens (e.g. 'my-skill')"))

    if not data.get("description", "").strip():
        errors.append(ValidationError("description", "Required: description is missing"))

    # Agents
    agents = data.get("agents", [])
    if not agents:
        errors.append(ValidationError("agents", "Required: at least one agent must be specified"))
    else:
        for a in agents:
            if a not in _VALID_AGENTS:
                errors.append(ValidationError(
                    "agents",
                    f"Unknown agent '{a}'. Valid: {', '.join(sorted(_VALID_AGENTS))}",
                    severity="warning",
                ))

    # Triggers
    triggers = data.get("triggers", {})
    keywords = triggers.get("keywords", []) if isinstance(triggers, dict) else []
    if not keywords:
        errors.append(ValidationError("triggers.keywords", "Required: at least one trigger keyword"))
    else:
        for i, kw in enumerate(keywords):
            try:
                re.compile(kw)
            except re.error as e:
                errors.append(ValidationError(
                    f"triggers.keywords[{i}]",
                    f"Invalid regex '{kw}': {e}",
                ))

    # Task types
    task_types = triggers.get("task_types", []) if isinstance(triggers, dict) else []
    for tt in task_types:
        if tt not in _VALID_TASK_TYPES:
            errors.append(ValidationError(
                "triggers.task_types",
                f"Unknown task type '{tt}'. Valid: {', '.join(sorted(_VALID_TASK_TYPES))}",
                severity="warning",
            ))

    # Instructions
    instructions = data.get("instructions", "")
    if not instructions.strip():
        errors.append(ValidationError("instructions", "Required: instructions are missing"))
    elif len(instructions.strip()) < 50:
        errors.append(ValidationError(
            "instructions",
            f"Instructions are very short ({len(instructions.strip())} chars). Consider adding more detail.",
            severity="warning",
        ))

    # Complexity
    hint = data.get("complexity_hint", "medium")
    if hint not in _VALID_COMPLEXITY:
        errors.append(ValidationError(
            "complexity_hint",
            f"Invalid value '{hint}'. Valid: {', '.join(sorted(_VALID_COMPLEXITY))}",
        ))

    return errors


def generate_template(name: str = "my-skill", description: str = "") -> str:
    """Generate a starter SKILL.yaml template with documented fields."""
    return f"""# Skill: {name}
# Drop this file in backend/agents/skills/catalog/{name}/SKILL.yaml
# Then call POST /api/v1/skills/reload to activate (no restart needed)

name: {name}
description: "{description or 'Brief description of what this skill does'}"
version: "1.0"

# Which agents can use this skill
# Valid: coder, researcher, browser, document_writer, validator, deerflow, hermes
agents:
  - coder

# When to activate this skill (regex patterns matched against the task goal)
triggers:
  keywords:
    - \\\\bmy-keyword\\\\b        # \\\\b = word boundary, ensures exact match
    - \\\\bother-keyword\\\\b
  task_types: [code]           # Optional: boost confidence when task type matches
                               # Valid: code, research, browser, document, deep_research, multi

# Instructions injected into the agent's context when this skill activates
# This is the core of your skill — be specific and actionable
instructions: |
  When working on [describe the scenario]:

  1. FIRST STEP
     - Detail what to do
     - Be specific about tools, patterns, or constraints

  2. SECOND STEP
     - More specific guidance
     - Include do's and don'ts

  3. THIRD STEP
     - Wrap up with quality checks

# Optional fields
tools: []                      # Tools required: e2b_sandbox, file_write, browser_use, etc.
complexity_hint: medium        # simple, medium, or complex
tags: []                       # Freeform tags for categorization
"""


class SkillRegistry:
    """Discovers, stores, and matches skills from SKILL.yaml catalog."""

    def __init__(self, catalog_dir: Path | None = None):
        self._catalog_dir = catalog_dir or _CATALOG_DIR
        self._skills: dict[str, SkillDefinition] = {}
        self._load_errors: dict[str, list[ValidationError]] = {}
        self._load_catalog()

    def _load_catalog(self):
        """Scan catalog directory for SKILL.yaml files and load them."""
        if not self._catalog_dir.exists():
            logger.info("Skills catalog dir %s does not exist — no skills loaded", self._catalog_dir)
            return

        for skill_dir in sorted(self._catalog_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.yaml"
            if not skill_file.exists():
                continue
            try:
                self._load_skill(skill_file)
            except Exception as e:
                logger.warning("Failed to load skill from %s: %s", skill_file, e)
                self._load_errors[skill_dir.name] = [
                    ValidationError("_file", f"YAML parse error: {e}")
                ]

        logger.info("Loaded %d skills from catalog", len(self._skills))

    def _load_skill(self, path: Path) -> SkillDefinition:
        """Load and validate a single SKILL.yaml file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            raise ValueError("Empty or invalid YAML")

        # Validate
        issues = validate_skill(data)
        errors = [e for e in issues if e.severity == "error"]
        warnings = [e for e in issues if e.severity == "warning"]

        name = data.get("name", path.parent.name)

        if warnings:
            for w in warnings:
                logger.warning("Skill '%s' warning: [%s] %s", name, w.field, w.message)
            self._load_errors[name] = warnings

        if errors:
            for e in errors:
                logger.error("Skill '%s' error: [%s] %s", name, e.field, e.message)
            self._load_errors[name] = issues
            raise ValueError(f"Validation failed: {errors[0].message}")

        triggers = data.get("triggers", {})
        skill = SkillDefinition(
            name=name,
            description=data.get("description", ""),
            version=str(data.get("version", "1.0")),
            agents=data.get("agents", []),
            triggers=triggers.get("keywords", []) if isinstance(triggers, dict) else [],
            task_types=triggers.get("task_types", []) if isinstance(triggers, dict) else [],
            instructions=data.get("instructions", ""),
            tools=data.get("tools", []),
            complexity_hint=data.get("complexity_hint", "medium"),
            tags=data.get("tags", []),
        )
        self._skills[name] = skill
        logger.debug("Loaded skill: %s (v%s, %d triggers)", name, skill.version, len(skill.triggers))
        return skill

    # ── Reload ────────────────────────────────────────────────────────────

    def reload(self) -> dict:
        """Hot-reload all skills from disk. Returns summary of changes."""
        old_names = set(self._skills.keys())
        self._skills.clear()
        self._load_errors.clear()
        self._load_catalog()
        new_names = set(self._skills.keys())

        return {
            "loaded": len(self._skills),
            "added": sorted(new_names - old_names),
            "removed": sorted(old_names - new_names),
            "unchanged": sorted(old_names & new_names),
            "errors": {k: [{"field": e.field, "message": e.message, "severity": e.severity} for e in v]
                       for k, v in self._load_errors.items()},
        }

    # ── Create ────────────────────────────────────────────────────────────

    def create_skill(self, data: dict) -> tuple[SkillDefinition, list[ValidationError]]:
        """Create a new skill from a dict, validate it, write SKILL.yaml, and register it.

        Args:
            data: Dict with skill fields (same structure as SKILL.yaml).

        Returns:
            Tuple of (created SkillDefinition, list of warnings).

        Raises:
            ValueError: If validation fails with errors.
        """
        issues = validate_skill(data)
        errors = [e for e in issues if e.severity == "error"]
        warnings = [e for e in issues if e.severity == "warning"]

        if errors:
            raise ValueError(
                "Validation failed:\n" +
                "\n".join(f"  [{e.field}] {e.message}" for e in errors)
            )

        name = data["name"]

        # Check for duplicate
        if name in self._skills:
            raise ValueError(f"Skill '{name}' already exists. Use a different name or delete it first.")

        # Build SkillDefinition
        triggers = data.get("triggers", {})
        skill = SkillDefinition(
            name=name,
            description=data.get("description", ""),
            version=str(data.get("version", "1.0")),
            agents=data.get("agents", []),
            triggers=triggers.get("keywords", []) if isinstance(triggers, dict) else [],
            task_types=triggers.get("task_types", []) if isinstance(triggers, dict) else [],
            instructions=data.get("instructions", ""),
            tools=data.get("tools", []),
            complexity_hint=data.get("complexity_hint", "medium"),
            tags=data.get("tags", []),
        )

        # Write to disk
        skill_dir = self._catalog_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.yaml"
        with open(skill_file, "w") as f:
            yaml.dump(skill.to_yaml_dict(), f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        # Register
        self._skills[name] = skill
        if warnings:
            self._load_errors[name] = warnings

        logger.info("Created skill '%s' at %s", name, skill_file)
        return skill, warnings

    def delete_skill(self, name: str) -> bool:
        """Delete a skill from registry and disk."""
        if name not in self._skills:
            return False

        # Remove from registry
        del self._skills[name]
        self._load_errors.pop(name, None)

        # Remove from disk
        skill_dir = self._catalog_dir / name
        skill_file = skill_dir / "SKILL.yaml"
        if skill_file.exists():
            skill_file.unlink()
        if skill_dir.exists() and not any(skill_dir.iterdir()):
            skill_dir.rmdir()

        logger.info("Deleted skill '%s'", name)
        return True

    # ── Query ─────────────────────────────────────────────────────────────

    def get(self, name: str) -> SkillDefinition | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        """Return all loaded skills."""
        return list(self._skills.values())

    def list_names(self) -> list[str]:
        """Return all skill names."""
        return list(self._skills.keys())

    def skills_for_agent(self, agent_name: str) -> list[SkillDefinition]:
        """Return skills compatible with a given agent."""
        return [s for s in self._skills.values() if agent_name in s.agents]

    def get_load_errors(self) -> dict[str, list[ValidationError]]:
        """Return any validation errors/warnings from the last load."""
        return self._load_errors

    # ── Matching ──────────────────────────────────────────────────────────

    def match(self, goal: str, task_type: str = "", top_k: int = 3) -> list[SkillMatch]:
        """Match a goal against the skill catalog.

        Returns up to top_k skills sorted by confidence (descending).
        """
        goal_lower = goal.lower()
        matches = []

        for skill in self._skills.values():
            # Score from trigger keyword matches
            matched = []
            for i, pattern in enumerate(skill.trigger_patterns):
                if pattern.search(goal_lower):
                    matched.append(skill.triggers[i] if i < len(skill.triggers) else "?")

            # Score from task_type match
            type_bonus = 0.2 if task_type and task_type in skill.task_types else 0.0

            if matched or type_bonus > 0:
                # Each match is worth 0.33 — a single match gives 0.33,
                # two matches give 0.67, three or more give 1.0.
                # This avoids penalizing skills with many triggers.
                keyword_score = min(len(matched) * 0.33, 1.0)
                confidence = min(keyword_score + type_bonus, 1.0)
                matches.append(SkillMatch(
                    skill=skill,
                    confidence=confidence,
                    matched_triggers=matched,
                ))

        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches[:top_k]

    def best_match(self, goal: str, task_type: str = "") -> SkillMatch | None:
        """Return the single best skill match, or None if no match."""
        matches = self.match(goal, task_type, top_k=1)
        return matches[0] if matches else None

    # ── Test ──────────────────────────────────────────────────────────────

    def test_skill(self, data: dict, sample_goals: list[str]) -> dict:
        """Dry-run a skill definition against sample goals without registering it.

        Returns validation results + matching preview.
        """
        # Validate
        issues = validate_skill(data)
        errors = [e for e in issues if e.severity == "error"]
        warnings = [e for e in issues if e.severity == "warning"]

        if errors:
            return {
                "valid": False,
                "errors": [{"field": e.field, "message": e.message} for e in errors],
                "warnings": [{"field": w.field, "message": w.message} for w in warnings],
                "matches": [],
            }

        # Build temporary skill
        triggers = data.get("triggers", {})
        skill = SkillDefinition(
            name=data.get("name", "test-skill"),
            description=data.get("description", ""),
            agents=data.get("agents", []),
            triggers=triggers.get("keywords", []) if isinstance(triggers, dict) else [],
            task_types=triggers.get("task_types", []) if isinstance(triggers, dict) else [],
            instructions=data.get("instructions", ""),
        )

        # Test against sample goals
        match_results = []
        for goal in sample_goals:
            goal_lower = goal.lower()
            matched = []
            for i, pattern in enumerate(skill.trigger_patterns):
                if pattern.search(goal_lower):
                    matched.append(skill.triggers[i] if i < len(skill.triggers) else "?")

            confidence = min(len(matched) * 0.33, 1.0) if matched else 0.0
            match_results.append({
                "goal": goal,
                "matched": len(matched) > 0,
                "confidence": round(confidence, 2),
                "matched_triggers": matched,
            })

        return {
            "valid": True,
            "errors": [],
            "warnings": [{"field": w.field, "message": w.message} for w in warnings],
            "matches": match_results,
        }

    # ── Instruction Injection ─────────────────────────────────────────────

    def get_instructions_for_task(
        self,
        goal: str,
        agent_name: str,
        task_type: str = "",
        min_confidence: float = 0.3,
    ) -> str:
        """Build skill instructions to inject into an agent's context."""
        matches = self.match(goal, task_type, top_k=5)

        parts = []
        for m in matches:
            if m.confidence < min_confidence:
                continue
            if agent_name not in m.skill.agents and m.skill.agents:
                continue
            if m.skill.instructions:
                parts.append(f"## Skill: {m.skill.name}\n{m.skill.instructions}")

        if not parts:
            return ""

        return "# Active Skills\n\n" + "\n\n".join(parts)

    # ── Orchestrator Helpers ──────────────────────────────────────────────

    def get_skill_hints_for_classification(self) -> str:
        """Build a summary of available skills for the orchestrator's classify prompt."""
        if not self._skills:
            return ""

        lines = ["Available skills (use these to inform agent selection):"]
        for skill in self._skills.values():
            agents_str = ", ".join(skill.agents) if skill.agents else "any"
            lines.append(f"  - {skill.name}: {skill.description} (agents: {agents_str})")
        return "\n".join(lines)

    def suggest_agents_for_goal(self, goal: str, task_type: str = "") -> list[str]:
        """Suggest which agents to use based on skill matches."""
        matches = self.match(goal, task_type, top_k=3)
        agents = []
        for m in matches:
            if m.confidence >= 0.3:
                agents.extend(m.skill.agents)
        # Deduplicate preserving order
        seen = set()
        result = []
        for a in agents:
            if a not in seen:
                seen.add(a)
                result.append(a)
        return result


# ── Singleton ─────────────────────────────────────────────────────────────
skill_registry = SkillRegistry()
