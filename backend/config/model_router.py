"""
AgentOS Model Router — cost-first routing with intelligent fallback.

Strategy: Use the cheapest capable model first, escalate to expensive models
only for complex tasks. Similar to Manus's cost optimization approach.

Cost tiers:
  - cheap-qwen ($0.00008/1K)  → simple tasks, validation, routing
  - workhorse-qwen ($0.0004/1K) → medium code, docs, research
  - workhorse-kimi ($0.0004/1K) → all browser tasks (tool-calling specialist)
  - workhorse-gemini ($0.0005/1K) → complex docs, medium research
  - workhorse/Sonnet ($0.003/1K) → complex code, complex research
  - orchestrator/Opus ($0.015/1K) → orchestration only

If Qwen/Kimi API keys are not configured, the router automatically
falls back to the next available model (Gemini → Sonnet).
"""

from dataclasses import dataclass

from config.settings import settings

# Model aliases (match litellm_config.yaml model_name values)
ORCHESTRATOR = "agentOS/orchestrator"
WORKHORSE = "agentOS/workhorse"
WORKHORSE_GEMINI = "agentOS/workhorse-gemini"
WORKHORSE_QWEN = "agentOS/workhorse-qwen"
WORKHORSE_KIMI = "agentOS/workhorse-kimi"
CHEAP = "agentOS/cheap"
CHEAP_QWEN = "agentOS/cheap-qwen"
FACTS = "agentOS/facts"
IMAGES = "agentOS/images"
ON_PREMISE = "agentOS/on-premise"

LITELLM_BASE_URL = "http://litellm:4000"


@dataclass
class ModelSelection:
    """Result of model routing decision."""
    model: str
    reason: str
    supplementary: str | None = None


# ── Fallback map: model → cheaper/available alternative ──────────────────

_FALLBACK_MAP: dict[str, str] = {
    WORKHORSE_QWEN: WORKHORSE_GEMINI,
    WORKHORSE_KIMI: WORKHORSE,
    CHEAP_QWEN: CHEAP,
}


def _is_model_available(model: str) -> bool:
    """Check if a model's API key is configured."""
    if model in (WORKHORSE_QWEN, CHEAP_QWEN):
        return bool(settings.qwen_api_key)
    if model == WORKHORSE_KIMI:
        return bool(settings.kimi_api_key)
    return True  # Anthropic/Google are always required


# ── Cost-first routing table ─────────────────────────────────────────────
# Priority: cheapest capable model first, Claude only for complex tasks

_ROUTING_TABLE: dict[tuple[str, str], ModelSelection] = {
    # orchestrate — always Opus (no substitute for planning)
    ("orchestrate", "simple"): ModelSelection(ORCHESTRATOR, "orchestration requires strongest reasoning"),
    ("orchestrate", "medium"): ModelSelection(ORCHESTRATOR, "orchestration requires strongest reasoning"),
    ("orchestrate", "complex"): ModelSelection(ORCHESTRATOR, "orchestration requires strongest reasoning"),

    # research — cheap-qwen → workhorse-qwen → workhorse (escalate by complexity)
    ("research", "simple"): ModelSelection(CHEAP_QWEN, "simple lookups use cheapest tier"),
    ("research", "medium"): ModelSelection(WORKHORSE_QWEN, "medium research uses cost-effective Qwen"),
    ("research", "complex"): ModelSelection(WORKHORSE, "complex research needs Claude Sonnet", FACTS),

    # code — cheap-qwen → workhorse-qwen → workhorse (escalate by complexity)
    ("code", "simple"): ModelSelection(CHEAP_QWEN, "simple code uses cheapest tier"),
    ("code", "medium"): ModelSelection(WORKHORSE_QWEN, "medium code uses cost-effective Qwen"),
    ("code", "complex"): ModelSelection(WORKHORSE, "complex code requires Claude Sonnet"),

    # browser — Kimi K2.5 is the specialist (massive tool-calling)
    ("browser", "simple"): ModelSelection(WORKHORSE_KIMI, "browser tasks use Kimi for tool-calling"),
    ("browser", "medium"): ModelSelection(WORKHORSE_KIMI, "browser tasks use Kimi for tool-calling"),
    ("browser", "complex"): ModelSelection(WORKHORSE_KIMI, "browser tasks use Kimi for tool-calling"),

    # document — cheap-qwen → workhorse-qwen → workhorse-gemini (escalate)
    ("document", "simple"): ModelSelection(CHEAP_QWEN, "simple docs use cheapest tier"),
    ("document", "medium"): ModelSelection(WORKHORSE_QWEN, "medium docs use cost-effective Qwen"),
    ("document", "complex"): ModelSelection(WORKHORSE_GEMINI, "complex docs benefit from Gemini context window"),

    # report — cheap-qwen → workhorse-qwen → workhorse-gemini (escalate)
    ("report", "simple"): ModelSelection(CHEAP_QWEN, "simple reports use cheapest tier"),
    ("report", "medium"): ModelSelection(WORKHORSE_QWEN, "medium reports use cost-effective Qwen"),
    ("report", "complex"): ModelSelection(WORKHORSE_GEMINI, "complex reports benefit from Gemini"),

    # route / validate — always cheapest
    ("route", "simple"): ModelSelection(CHEAP_QWEN, "routing decisions use cheapest tier"),
    ("route", "medium"): ModelSelection(CHEAP_QWEN, "routing decisions use cheapest tier"),
    ("route", "complex"): ModelSelection(CHEAP_QWEN, "routing decisions use cheapest tier"),
    ("validate", "simple"): ModelSelection(CHEAP_QWEN, "validation uses cheapest tier"),
    ("validate", "medium"): ModelSelection(CHEAP_QWEN, "validation uses cheapest tier"),
    ("validate", "complex"): ModelSelection(CHEAP_QWEN, "validation uses cheapest tier"),
}

VALID_TASK_TYPES = {"orchestrate", "research", "code", "browser", "document", "report", "route", "validate"}
VALID_COMPLEXITIES = {"simple", "medium", "complex"}


def select_model(task_type: str, complexity: str = "medium") -> ModelSelection:
    """Select the optimal model for a given task type and complexity.

    Uses cost-first routing: cheapest capable model is preferred.
    If the selected model's API key is not configured, automatically
    falls back to the next available alternative.

    Args:
        task_type: One of "orchestrate", "research", "code", "browser",
                   "document", "report", "route", "validate".
        complexity: One of "simple", "medium", "complex".

    Returns:
        ModelSelection with model name, reason, and optional supplementary model.

    Raises:
        ValueError: If task_type or complexity is not recognized.
    """
    if task_type not in VALID_TASK_TYPES:
        raise ValueError(f"Unknown task_type '{task_type}'. Valid: {VALID_TASK_TYPES}")
    if complexity not in VALID_COMPLEXITIES:
        raise ValueError(f"Unknown complexity '{complexity}'. Valid: {VALID_COMPLEXITIES}")

    selection = _ROUTING_TABLE[(task_type, complexity)]

    # Apply fallback if the preferred model's API key is not configured
    if not _is_model_available(selection.model):
        fallback = _FALLBACK_MAP.get(selection.model)
        if fallback:
            return ModelSelection(
                model=fallback,
                reason=f"{selection.reason} (fallback: {selection.model} not configured)",
                supplementary=selection.supplementary,
            )

    return selection
