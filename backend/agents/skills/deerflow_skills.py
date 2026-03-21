"""DeerFlow skill routing — maps AgentOS task intents to DeerFlow 2.0 skills.

DeerFlow ships with built-in skills (Markdown-based workflow definitions):
  - research: Deep multi-source web research with citations
  - slides: Generate presentation decks (PPTX)
  - report: Comprehensive reports with data and charts
  - code: Code execution with sandbox (bash + Python + filesystem)
  - webpage: Generate complete web pages
  - image: Generate images via AI models
  - video: Generate or edit video content

This module provides routing logic to select the best DeerFlow skill
based on the AgentOS task description and type.
"""

import re
from dataclasses import dataclass


@dataclass
class SkillMatch:
    """Result of skill matching."""
    skill: str | None  # None means let DeerFlow auto-route
    confidence: float  # 0.0 to 1.0
    reason: str


# Keyword patterns for skill detection
_SKILL_PATTERNS: list[tuple[str, list[str]]] = [
    ("research", [
        r"\bresearch\b", r"\binvestigat\w+", r"\banalyz\w+\s+(?:data|trend|market)",
        r"\bcomprehensive\s+(?:review|analysis|report)\b", r"\bliterature\s+review\b",
        r"\bcompare\s+(?:and\s+)?contrast\b", r"\bstate\s+of\s+the\s+art\b",
        r"\bdeep\s+dive\b", r"\bsources?\s+and\s+citations?\b",
    ]),
    ("slides", [
        r"\bpresentation\b", r"\bslide\s*(?:s|deck)?\b", r"\bpptx?\b",
        r"\bpowerpoint\b", r"\bkeynote\b", r"\bpitch\s+deck\b",
    ]),
    ("code", [
        r"\bexecut\w+\s+(?:code|script|program)\b", r"\brun\s+(?:this|the)\s+(?:code|script)\b",
        r"\bbuild\s+(?:a|an|the)\s+(?:app|tool|script|dashboard)\b",
        r"\bwrite\s+(?:a|an)\s+(?:script|program|tool)\b",
        r"\bdata\s+(?:pipeline|processing|etl)\b",
        r"\bscrape\s+(?:and\s+)?(?:analyz|process)\b",
    ]),
    ("report", [
        r"\breport\b", r"\bwhite\s*paper\b", r"\bdocument\s+(?:about|on|for)\b",
        r"\bsummar(?:y|ize)\b.*\bdetailed\b", r"\bexecutive\s+summary\b",
    ]),
]


def match_skill(goal: str, task_type: str = "") -> SkillMatch:
    """Determine the best DeerFlow skill for a given goal.

    Args:
        goal: The user's task description.
        task_type: Optional task type from classification.

    Returns:
        SkillMatch with recommended skill and confidence.
    """
    goal_lower = goal.lower()

    # Direct task_type mapping (high confidence)
    type_map = {
        "deep_research": ("research", 0.9, "Task classified as deep research"),
        "document": ("slides", 0.7, "Task classified as document generation"),
    }
    if task_type in type_map:
        return SkillMatch(*type_map[task_type])

    # Pattern matching
    best_skill = None
    best_score = 0.0
    best_reason = ""

    for skill_name, patterns in _SKILL_PATTERNS:
        matches = 0
        for pattern in patterns:
            if re.search(pattern, goal_lower):
                matches += 1

        if matches > 0:
            score = min(matches / 3, 1.0)  # Cap at 1.0
            if score > best_score:
                best_skill = skill_name
                best_score = score
                best_reason = f"Matched {matches} pattern(s) for '{skill_name}'"

    if best_skill and best_score >= 0.3:
        return SkillMatch(skill=best_skill, confidence=best_score, reason=best_reason)

    # Default: let DeerFlow auto-route
    return SkillMatch(skill=None, confidence=0.5, reason="No strong skill match — DeerFlow will auto-route")


def should_use_deerflow(goal: str, task_type: str, complexity: str) -> bool:
    """Determine if a task should be routed to DeerFlow instead of native agents.

    Returns True for tasks where DeerFlow's capabilities clearly exceed
    the native AgentOS agents.
    """
    # Always use DeerFlow for deep research
    if task_type == "deep_research":
        return True

    # Always use DeerFlow for complex multi-step tasks
    if complexity == "complex" and task_type == "multi":
        return True

    # Use DeerFlow for tasks that need sandbox execution
    goal_lower = goal.lower()
    sandbox_signals = [
        "execute", "run the code", "run this", "build and test",
        "data pipeline", "scrape and analyze", "dashboard",
    ]
    if any(s in goal_lower for s in sandbox_signals):
        return True

    # Use DeerFlow for presentation/report generation
    match = match_skill(goal, task_type)
    if match.skill in ("slides", "report") and match.confidence >= 0.5:
        return True

    return False
