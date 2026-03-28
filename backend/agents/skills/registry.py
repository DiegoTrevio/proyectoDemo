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
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("agentos.skills.registry")

_CATALOG_DIR = Path(__file__).parent / "catalog"


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
                    # Treat as literal keyword
                    self._compiled_patterns.append(re.compile(re.escape(kw), re.IGNORECASE))
        return self._compiled_patterns


@dataclass
class SkillMatch:
    """Result of matching a goal against the skill catalog."""

    skill: SkillDefinition
    confidence: float  # 0.0 to 1.0
    matched_triggers: list[str]


class SkillRegistry:
    """Discovers, stores, and matches skills from SKILL.yaml catalog."""

    def __init__(self, catalog_dir: Path | None = None):
        self._catalog_dir = catalog_dir or _CATALOG_DIR
        self._skills: dict[str, SkillDefinition] = {}
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

        logger.info("Loaded %d skills from catalog", len(self._skills))

    def _load_skill(self, path: Path):
        """Load a single SKILL.yaml file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            return

        name = data.get("name", path.parent.name)
        skill = SkillDefinition(
            name=name,
            description=data.get("description", ""),
            version=str(data.get("version", "1.0")),
            agents=data.get("agents", []),
            triggers=data.get("triggers", {}).get("keywords", []),
            task_types=data.get("triggers", {}).get("task_types", []),
            instructions=data.get("instructions", ""),
            tools=data.get("tools", []),
            complexity_hint=data.get("complexity_hint", "medium"),
            tags=data.get("tags", []),
        )
        self._skills[name] = skill
        logger.debug("Loaded skill: %s (v%s, %d triggers)", name, skill.version, len(skill.triggers))

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

    # ── Instruction Injection ─────────────────────────────────────────────

    def get_instructions_for_task(
        self,
        goal: str,
        agent_name: str,
        task_type: str = "",
        min_confidence: float = 0.3,
    ) -> str:
        """Build skill instructions to inject into an agent's context.

        Returns a formatted string with instructions from all matching skills
        that are compatible with the given agent, above the confidence threshold.
        """
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
