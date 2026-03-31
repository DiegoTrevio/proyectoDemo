"""Hermes-first router — deterministic, zero-LLM-call task classifier.

Phase 2: Decides whether a task should bypass the LangGraph orchestrator
and go directly to Hermes Agent. Uses keyword heuristics instead of an
LLM call, saving ~$0.03-0.05 and 5-15 seconds per qualifying task.
"""

import logging
import re

from config.settings import settings

logger = logging.getLogger("agentos.hermes_router")

# ─── Exclusion patterns (tasks that should NOT go Hermes-first) ──────────

_EXCLUDE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"deep\s+research",
        r"comprehensive\s+analysis",
        r"multi[- ]source",
        r"with\s+citations",
        r"literature\s+review",
        r"slide\s*deck",
        r"presentation",
        r"dashboard",
        r"pdf\s+report",
        r"formatted\s+document",
        r"powerpoint|pptx|docx|xlsx",
    ]
]

# ─── Inclusion patterns (tasks that Hermes handles well natively) ────────

_INCLUDE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        # Code tasks
        r"write\s+(a\s+)?function",
        r"write\s+(a\s+)?script",
        r"write\s+(a\s+)?program",
        r"fix\s+(this\s+)?bug",
        r"create\s+(a\s+)?(script|class|module|file|component)",
        r"refactor",
        r"debug",
        r"implement\s+(a\s+)?",
        r"add\s+(a\s+)?(feature|endpoint|route|test)",
        # Research / lookup
        r"search\s+for",
        r"find\s+information",
        r"look\s+up",
        r"^what\s+is\b",
        r"^how\s+(to|do|does)\b",
        r"^explain\b",
        # File operations
        r"read\s+(the\s+)?file",
        r"edit\s+(the\s+)?file",
        r"create\s+(a\s+)?file",
        r"list\s+(the\s+)?files",
        r"rename\s+",
        r"delete\s+(the\s+)?file",
        # General tasks
        r"run\s+(the\s+)?(command|test|script)",
        r"install\s+",
        r"update\s+(the\s+)?",
        r"check\s+(the\s+)?",
    ]
]

# Max goal length for Hermes-first (very long goals suggest complex tasks)
_MAX_GOAL_LENGTH = 2000
# Short goals that don't match exclusions are good candidates
_SHORT_GOAL_THRESHOLD = 500


def should_route_hermes_first(goal: str, config: dict | None = None) -> bool:
    """Decide whether a task should bypass the orchestrator and go directly to Hermes.

    Returns True if the task qualifies for Hermes-first routing. Uses deterministic
    keyword heuristics — no LLM calls.

    Args:
        goal: The user's task description.
        config: Optional task config dict. May contain explicit routing_mode override.

    Returns:
        True if the task should go directly to Hermes.
    """
    # Feature flag check
    if not settings.hermes_first_enabled or not settings.hermes_enabled:
        return False

    # Honor explicit routing_mode overrides from API
    if config:
        routing_mode = config.get("routing_mode")
        if routing_mode == "hermes_first":
            logger.debug("Explicit hermes_first routing requested")
            return True
        if routing_mode == "orchestrator":
            logger.debug("Explicit orchestrator routing requested")
            return False
        # "auto" or None → continue to heuristics

    goal_stripped = goal.strip()

    # Reject very long goals (likely complex)
    if len(goal_stripped) > _MAX_GOAL_LENGTH:
        logger.debug("Goal too long (%d chars) for hermes-first", len(goal_stripped))
        return False

    # Check exclusion patterns first
    for pattern in _EXCLUDE_PATTERNS:
        if pattern.search(goal_stripped):
            logger.debug("Goal matches exclusion pattern: %s", pattern.pattern)
            return False

    # Check inclusion patterns
    for pattern in _INCLUDE_PATTERNS:
        if pattern.search(goal_stripped):
            logger.info("Hermes-first: goal matches inclusion pattern '%s'", pattern.pattern)
            return True

    # Short, non-excluded goals are good candidates
    if len(goal_stripped) <= _SHORT_GOAL_THRESHOLD:
        logger.info("Hermes-first: short goal (%d chars), no exclusion match", len(goal_stripped))
        return True

    # Default: conservative — go through full orchestrator
    logger.debug("Goal does not match hermes-first heuristics, using orchestrator")
    return False


def select_toolsets_for_goal(goal: str) -> list[str] | None:
    """Select Hermes toolsets based on goal keywords.

    Returns a list of toolset names to enable, or None to let Hermes use all tools.

    Args:
        goal: The user's task description.
    """
    goal_lower = goal.lower()

    code_keywords = ("code", "function", "script", "debug", "refactor", "implement",
                     "class", "module", "test", "compile", "build", "lint")
    research_keywords = ("search", "find", "look up", "research", "information",
                         "what is", "how to", "explain")
    file_keywords = ("file", "read", "write", "edit", "create", "rename", "delete",
                     "directory", "folder")
    browser_keywords = ("browse", "navigate", "website", "url", "page", "click",
                        "form", "scrape", "extract")

    if any(kw in goal_lower for kw in browser_keywords):
        return ["browser", "web"]
    if any(kw in goal_lower for kw in code_keywords):
        return ["terminal", "file", "code_execution"]
    if any(kw in goal_lower for kw in file_keywords):
        return ["terminal", "file"]
    if any(kw in goal_lower for kw in research_keywords):
        return ["web", "browser"]

    # Default: let Hermes decide (all tools available)
    return None
