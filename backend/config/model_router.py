"""
AgentOS Model Router — selects the optimal LLM model based on task type and complexity.

Routes requests to the appropriate LiteLLM model alias defined in litellm_config.yaml.
"""

from dataclasses import dataclass

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


# Routing table: (task_type, complexity) -> ModelSelection
_ROUTING_TABLE: dict[tuple[str, str], ModelSelection] = {
    # orchestrate — always Opus
    ("orchestrate", "simple"): ModelSelection(ORCHESTRATOR, "orchestration requires strongest reasoning"),
    ("orchestrate", "medium"): ModelSelection(ORCHESTRATOR, "orchestration requires strongest reasoning"),
    ("orchestrate", "complex"): ModelSelection(ORCHESTRATOR, "orchestration requires strongest reasoning"),
    # research
    ("research", "simple"): ModelSelection(CHEAP, "simple lookups use cheap tier"),
    ("research", "medium"): ModelSelection(WORKHORSE_GEMINI, "medium research benefits from Gemini context window"),
    ("research", "complex"): ModelSelection(WORKHORSE, "complex research needs Claude Sonnet", FACTS),
    # code
    ("code", "simple"): ModelSelection(WORKHORSE_QWEN, "simple code tasks use Qwen"),
    ("code", "medium"): ModelSelection(WORKHORSE, "medium code tasks use Claude Sonnet"),
    ("code", "complex"): ModelSelection(WORKHORSE, "complex code requires Claude Sonnet"),
    # browser
    ("browser", "simple"): ModelSelection(WORKHORSE_KIMI, "browser tasks use Kimi for massive tool-calling"),
    ("browser", "medium"): ModelSelection(WORKHORSE_KIMI, "browser tasks use Kimi for massive tool-calling"),
    ("browser", "complex"): ModelSelection(WORKHORSE_KIMI, "browser tasks use Kimi for massive tool-calling"),
    # document
    ("document", "simple"): ModelSelection(WORKHORSE_QWEN, "simple docs use Qwen"),
    ("document", "medium"): ModelSelection(WORKHORSE_GEMINI, "medium docs benefit from Gemini context window"),
    ("document", "complex"): ModelSelection(WORKHORSE_GEMINI, "complex docs benefit from Gemini context window"),
    # report
    ("report", "simple"): ModelSelection(WORKHORSE_QWEN, "simple reports use Qwen"),
    ("report", "medium"): ModelSelection(WORKHORSE_GEMINI, "medium reports benefit from Gemini"),
    ("report", "complex"): ModelSelection(WORKHORSE, "complex reports need Claude Sonnet"),
    # route / validate — always cheap
    ("route", "simple"): ModelSelection(CHEAP, "routing decisions use cheap tier"),
    ("route", "medium"): ModelSelection(CHEAP, "routing decisions use cheap tier"),
    ("route", "complex"): ModelSelection(CHEAP, "routing decisions use cheap tier"),
    ("validate", "simple"): ModelSelection(CHEAP, "validation uses cheap tier"),
    ("validate", "medium"): ModelSelection(CHEAP, "validation uses cheap tier"),
    ("validate", "complex"): ModelSelection(CHEAP, "validation uses cheap tier"),
}

VALID_TASK_TYPES = {"orchestrate", "research", "code", "browser", "document", "report", "route", "validate"}
VALID_COMPLEXITIES = {"simple", "medium", "complex"}


def select_model(task_type: str, complexity: str = "medium") -> ModelSelection:
    """Select the optimal model for a given task type and complexity.

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

    return _ROUTING_TABLE[(task_type, complexity)]
