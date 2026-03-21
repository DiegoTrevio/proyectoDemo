"""Validator Agent — reviews, lints, and tests outputs from other agents.

Validates:
  - Code quality (syntax, common bugs, security issues)
  - Document structure and completeness
  - Research accuracy and source quality
  - General output coherence and goal alignment

Model routing:
  - Quick validation → agentOS/cheap (Gemini Flash Lite)
  - Deep review → agentOS/workhorse (Sonnet)
"""

import json
import logging

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

logger = logging.getLogger("agentos.agents.validator")

_SYSTEM_PROMPT = """You are a strict quality validator. Your job is to review outputs from other AI agents and check for:

1. **Correctness**: Does the output actually address the goal?
2. **Completeness**: Is anything missing or incomplete?
3. **Code quality** (if code): Syntax errors, security vulnerabilities (injection, XSS, hardcoded secrets), missing error handling
4. **Factual accuracy** (if research): Unsupported claims, outdated info, missing sources
5. **Document quality** (if document): Structure, clarity, professionalism

Rules:
- Be strict but fair — flag real issues, not style preferences
- Always respond with valid JSON
- Include specific line/section references when possible
- Suggest fixes for every issue found"""

_VALIDATE_PROMPT = """Validate this output against the original goal.

**Original goal:** {goal}

**Agent that produced this:** {agent}

**Output to validate:**
{output}

Respond with JSON only:
{{
  "passed": true|false,
  "score": 0.0-1.0,
  "issues": [
    {{"severity": "critical"|"warning"|"info", "description": "...", "suggestion": "..."}}
  ],
  "summary": "Brief validation summary"
}}"""

_CODE_REVIEW_PROMPT = """Review this code for security vulnerabilities, bugs, and quality issues.

**Code:**
```
{code}
```

**Context:** {context}

Respond with JSON only:
{{
  "passed": true|false,
  "score": 0.0-1.0,
  "security_issues": [
    {{"severity": "critical"|"high"|"medium"|"low", "type": "...", "description": "...", "fix": "..."}}
  ],
  "bugs": [
    {{"description": "...", "fix": "..."}}
  ],
  "summary": "Brief review summary"
}}"""


class ValidatorAgent(AbstractAgent):
    """Reviews and validates outputs from other agents."""

    name = "validator"
    task_type = "code"
    default_complexity = "simple"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None):
        cb_config = CircuitBreakerConfig(
            max_iterations=4,
            timeout_seconds=120,
            max_cost_per_task=1.0,
        )
        super().__init__(circuit_breaker or CircuitBreaker(cb_config))

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Validate an output from another agent."""
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")
        cb_state = self.cb.new_state()

        # Get prior results to validate
        prior_results = context.get("prior_results", [])
        if not prior_results:
            return AgentResult(
                success=True,
                output="No prior results to validate.",
                tokens_used=0,
                cost=0.0,
            )

        all_issues = []
        all_summaries = []
        overall_passed = True
        total_score = 0.0

        for result in prior_results:
            if not result.get("success"):
                continue

            output = result.get("output", "")
            agent = result.get("agent", "unknown")

            if not output.strip():
                continue

            # Determine if this is code or general output
            is_code = agent == "coder" or _looks_like_code(output)

            if is_code:
                prompt = _CODE_REVIEW_PROMPT.format(
                    code=output[:8000],
                    context=goal[:500],
                )
            else:
                prompt = _VALIDATE_PROMPT.format(
                    goal=goal[:500],
                    agent=agent,
                    output=output[:8000],
                )

            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            try:
                model = "agentOS/cheap" if len(output) < 2000 else "agentOS/workhorse"
                response_text, cb_state = await self.call_llm(
                    messages, cb_state, model_override=model, max_tokens=2048,
                )
                validation = _parse_json(response_text)

                passed = validation.get("passed", True)
                score = validation.get("score", 0.5)
                issues = validation.get("issues", []) + validation.get("security_issues", []) + validation.get("bugs", [])
                summary = validation.get("summary", "")

                if not passed:
                    overall_passed = False

                total_score += score
                all_issues.extend(issues)
                all_summaries.append(f"[{agent}] {summary}")

            except Exception as e:
                logger.warning("Validation failed for %s output: %s", agent, e)
                all_summaries.append(f"[{agent}] Validation error: {e}")

        # Compile final report
        num_validated = max(len(all_summaries), 1)
        avg_score = total_score / num_validated

        critical_issues = [i for i in all_issues if i.get("severity") in ("critical", "high")]
        warnings = [i for i in all_issues if i.get("severity") in ("warning", "medium")]

        report_lines = [
            f"Validation {'PASSED' if overall_passed else 'FAILED'} (score: {avg_score:.1%})",
            f"Validated {num_validated} output(s): {len(critical_issues)} critical, {len(warnings)} warnings",
            "",
        ]

        for summary in all_summaries:
            report_lines.append(f"  {summary}")

        if critical_issues:
            report_lines.append("\nCritical Issues:")
            for issue in critical_issues:
                desc = issue.get("description", issue.get("type", "Unknown"))
                fix = issue.get("suggestion", issue.get("fix", ""))
                report_lines.append(f"  - {desc}")
                if fix:
                    report_lines.append(f"    Fix: {fix}")

        if warnings:
            report_lines.append("\nWarnings:")
            for issue in warnings:
                desc = issue.get("description", "")
                report_lines.append(f"  - {desc}")

        report = "\n".join(report_lines)

        return AgentResult(
            success=True,
            output=report,
            tokens_used=cb_state.tokens_used,
            cost=cb_state.total_cost,
        )


def _looks_like_code(text: str) -> bool:
    """Heuristic to detect if output contains code."""
    code_indicators = [
        "def ", "class ", "import ", "function ", "const ", "let ", "var ",
        "```", "return ", "if (", "for (", "while (", "try:", "except:",
    ]
    return any(indicator in text for indicator in code_indicators)


def _parse_json(text: str) -> dict:
    """Extract JSON from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)
