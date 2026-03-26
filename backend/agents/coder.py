"""Coder Agent — generates, executes, and iterates on code.

Model routing:
  - <100 lines estimated -> Qwen (agentOS/workhorse-qwen)
  - >100 lines -> Claude Sonnet (agentOS/workhorse)
  - Architecture/complex design -> Claude Opus (agentOS/orchestrator)

For complex tasks (>100 lines estimated), uses Superpowers skills:
  1. brainstorming -> generate spec
  2. executing-plans -> generate plan
  3. test-driven-development -> write tests first
  4. Implement code following TDD (red/green)
  5. systematic-debugging if errors
  6. requesting-code-review -> self-review

Circuit breakers (coder-specific):
  - Max executions per task: 5
  - Max consecutive failures: 3
  - Max total time: 5 minutes
"""

import json
import logging
import os

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from config.model_router import ORCHESTRATOR, select_model
from tools.code_executor import CodeExecutor

logger = logging.getLogger("agentos.agents.coder")

_MAX_EXECUTIONS = 5
_MAX_CONSECUTIVE_FAILURES = 3
_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills", "superpowers")

_SYSTEM_PROMPT = """You are an expert software engineer. You write clean, correct, production-quality code.

Rules:
1. Write complete, runnable code — no placeholders or TODOs
2. Include all necessary imports
3. If generating a chart/plot, always call plt.savefig('output.png') AND plt.show()
4. Handle edge cases gracefully
5. Use type hints where appropriate
6. Keep code minimal — don't over-engineer"""

_GENERATE_PROMPT = """Write code to accomplish this task:

{goal}

{context_section}

Respond with JSON only:
{{
  "language": "python",
  "code": "the complete runnable code",
  "dependencies": ["pip_package1", "pip_package2"],
  "estimated_lines": 50,
  "explanation": "brief explanation of approach"
}}"""

_FIX_PROMPT = """The code failed with this error. Fix it.

Original task: {goal}

Code that failed:
```{language}
{code}
```

Error output:
```
{error}
```

Stdout so far:
```
{stdout}
```

Attempt {attempt} of {max_attempts}.

Respond with JSON only:
{{
  "code": "the fixed complete runnable code",
  "dependencies": ["any_new_deps"],
  "explanation": "what was wrong and how you fixed it"
}}"""

_SUPERPOWERS_PROMPT = """You are following Superpowers methodology for complex code tasks.

{skill_content}

---

Apply this skill to the following task:

{goal}

{context_section}

Respond with JSON only:
{{
  "language": "python",
  "code": "the complete runnable code",
  "tests": "test code (pytest)",
  "dependencies": ["pip_package1"],
  "estimated_lines": 100,
  "explanation": "approach with skill methodology applied",
  "review_notes": "self-review findings"
}}"""


def _load_skill(name: str) -> str:
    """Load a Superpowers skill markdown file."""
    path = os.path.join(_SKILLS_DIR, f"{name}.md")
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Skill file not found: %s", path)
        return ""


class CoderAgent(AbstractAgent):
    """Generates and executes code with iterative error correction."""

    name = "coder"
    task_type = "code"
    default_complexity = "medium"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None):
        cb_config = CircuitBreakerConfig(
            max_iterations=_MAX_EXECUTIONS * 2,  # LLM calls + executions
            timeout_seconds=300,
        )
        super().__init__(circuit_breaker or CircuitBreaker(cb_config))
        self.executor = CodeExecutor()

    def _select_model(self, goal: str, estimated_lines: int = 50) -> str:
        """Select model based on task complexity, delegating to the central router."""
        goal_lower = goal.lower()

        # Architecture-level tasks -> Opus (always escalate)
        arch_signals = ["architect", "design system", "microservice", "database schema",
                        "api design", "system design"]
        if any(s in goal_lower for s in arch_signals):
            return ORCHESTRATOR

        # Delegate to cost-first router with fallback support
        complexity = "simple" if estimated_lines < 100 else "medium"
        return select_model("code", complexity).model

    def _parse_json_response(self, text: str) -> dict:
        """Extract JSON from LLM response, handling code fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        return json.loads(text)

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Generate code, execute in sandbox, iterate on errors.

        For complex tasks (>100 estimated lines), uses Superpowers methodology.
        """
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")

        cb_state = self.cb.new_state()
        executions = 0
        consecutive_failures = 0
        current_code = ""
        language = "python"
        dependencies: list[str] = []
        last_stdout = ""
        last_stderr = ""

        # Build context section from prior results
        context_section = ""
        prior = context.get("prior_results", [])
        if prior:
            context_section = "Context from previous steps:\n"
            for r in prior[-3:]:
                context_section += f"- {r.get('output', '')[:200]}\n"

        # ── Step 1: Generate initial code ──
        logger.info("Coder generating code for: %s", goal[:80])

        # Estimate complexity from goal length and keywords
        complex_signals = ["full application", "complete system", "multi-file",
                           "architecture", "refactor entire", "build a"]
        is_complex = any(s in goal.lower() for s in complex_signals) or len(goal) > 500

        if is_complex:
            # Use Superpowers methodology
            response_text, cb_state, estimated_lines = await self._superpowers_generate(
                goal, context_section, cb_state,
            )
        else:
            response_text = None
            estimated_lines = 50

        if response_text is None:
            # Standard generation
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _GENERATE_PROMPT.format(
                    goal=goal, context_section=context_section,
                )},
            ]
            model = self._select_model(goal)
            try:
                response_text, cb_state = await self.call_llm(
                    messages, cb_state, model_override=model, max_tokens=8192,
                )
            except Exception as e:
                logger.exception("Code generation failed")
                return AgentResult(
                    success=False, output="", error=f"Code generation failed: {e}",
                    tokens_used=cb_state.tokens_used, cost=cb_state.total_cost,
                )

        # Parse response
        try:
            parsed = self._parse_json_response(response_text)
            current_code = parsed.get("code", "")
            language = parsed.get("language", "python")
            dependencies = parsed.get("dependencies", [])
            estimated_lines = parsed.get("estimated_lines", estimated_lines)

            if not current_code:
                return AgentResult(
                    success=False, output="", error="LLM returned empty code",
                    tokens_used=cb_state.tokens_used, cost=cb_state.total_cost,
                )
        except json.JSONDecodeError:
            current_code = self._extract_code_from_text(response_text)
            if not current_code:
                return AgentResult(
                    success=False, output="", error="Could not parse LLM response as code",
                    tokens_used=cb_state.tokens_used, cost=cb_state.total_cost,
                )

        # Auto-detect dependencies if none specified
        if not dependencies:
            dependencies = self.executor._detect_dependencies(current_code)

        # ── HITL: validate before executing arbitrary code ──
        await self.validate_tool_call(task_id, "code_execute", current_code[:500])

        # ── Step 2: Execute + iterate loop ──
        while executions < _MAX_EXECUTIONS and consecutive_failures < _MAX_CONSECUTIVE_FAILURES:
            if cb_state.tripped:
                logger.warning("Circuit breaker tripped: %s", cb_state.trip_reason)
                break

            executions += 1
            logger.info("Executing code attempt %d/%d", executions, _MAX_EXECUTIONS)

            exec_result = await self.executor.execute(
                code=current_code,
                language=language,
                dependencies=dependencies,
            )

            last_stdout = exec_result.stdout
            last_stderr = exec_result.stderr

            if exec_result.success:
                logger.info("Code executed successfully on attempt %d", executions)
                output_parts = []
                if exec_result.stdout:
                    output_parts.append(exec_result.stdout)

                artifacts = []
                for f in exec_result.files:
                    artifacts.append({
                        "type": "file",
                        "name": f["name"],
                        "content_b64": f.get("content_b64", ""),
                    })

                return AgentResult(
                    success=True,
                    output="\n".join(output_parts) if output_parts else "Code executed successfully.",
                    artifacts=artifacts,
                    tokens_used=cb_state.tokens_used,
                    cost=cb_state.total_cost,
                )

            # Execution failed — try to fix
            consecutive_failures += 1
            error_msg = exec_result.error or exec_result.stderr or "Unknown error"
            logger.warning("Execution failed (attempt %d): %s", executions, error_msg[:200])

            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                break

            # Use systematic-debugging skill for complex errors
            if is_complex and consecutive_failures >= 2:
                fix_response, cb_state = await self._debug_with_skill(
                    goal, current_code, language, error_msg, last_stdout, executions, cb_state,
                )
            else:
                # Standard fix
                fix_messages = [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _FIX_PROMPT.format(
                        goal=goal, language=language, code=current_code,
                        error=error_msg[:2000], stdout=last_stdout[:1000],
                        attempt=executions, max_attempts=_MAX_EXECUTIONS,
                    )},
                ]
                try:
                    model = self._select_model(goal, estimated_lines)
                    fix_response, cb_state = await self.call_llm(
                        fix_messages, cb_state, model_override=model, max_tokens=8192,
                    )
                except Exception as e:
                    logger.warning("Fix generation failed: %s", e)
                    continue

            try:
                fix_parsed = self._parse_json_response(fix_response)
                current_code = fix_parsed.get("code", current_code)
                new_deps = fix_parsed.get("dependencies", [])
                if new_deps:
                    dependencies = list(set(dependencies + new_deps))
                consecutive_failures = 0  # Reset on successful fix generation
            except Exception as e:
                logger.warning("Fix parse failed: %s", e)

        # All attempts exhausted
        return AgentResult(
            success=False,
            output=last_stdout,
            error=f"Code failed after {executions} attempts. Last error: {last_stderr or 'unknown'}",
            tokens_used=cb_state.tokens_used,
            cost=cb_state.total_cost,
        )

    async def _superpowers_generate(
        self,
        goal: str,
        context_section: str,
        cb_state,
    ) -> tuple[str | None, object, int]:
        """Generate code using Superpowers methodology for complex tasks.

        Loads brainstorming, executing-plans, TDD, and code-review skills.
        Returns (response_text, cb_state, estimated_lines) or (None, cb_state, 50) on failure.
        """
        logger.info("Using Superpowers methodology for complex task")

        # Combine relevant skills
        skills = [
            _load_skill("brainstorming"),
            _load_skill("executing-plans"),
            _load_skill("test-driven-development"),
            _load_skill("requesting-code-review"),
        ]
        combined_skills = "\n\n---\n\n".join(s for s in skills if s)

        if not combined_skills:
            return None, cb_state, 50

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _SUPERPOWERS_PROMPT.format(
                skill_content=combined_skills[:6000],
                goal=goal,
                context_section=context_section,
            )},
        ]

        model = self._select_model(goal, estimated_lines=200)  # Force powerful model
        try:
            response_text, cb_state = await self.call_llm(
                messages, cb_state, model_override=model, max_tokens=16384,
            )
            return response_text, cb_state, 200
        except Exception as e:
            logger.warning("Superpowers generation failed, falling back: %s", e)
            return None, cb_state, 50

    async def _debug_with_skill(
        self,
        goal: str,
        code: str,
        language: str,
        error: str,
        stdout: str,
        attempt: int,
        cb_state,
    ) -> tuple[str, object]:
        """Use systematic-debugging skill for complex error resolution."""
        debug_skill = _load_skill("systematic-debugging")

        prompt = f"""{debug_skill}

---

Apply systematic debugging to fix this error:

Task: {goal}

Code:
```{language}
{code}
```

Error:
```
{error[:2000]}
```

Stdout:
```
{stdout[:1000]}
```

Attempt {attempt} of {_MAX_EXECUTIONS}.

Follow the systematic debugging process. Respond with JSON:
{{
  "hypothesis": "what you think is wrong",
  "code": "the fixed complete runnable code",
  "dependencies": ["any_new_deps"],
  "explanation": "diagnosis and fix"
}}"""

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        model = self._select_model(goal, estimated_lines=200)
        return await self.call_llm(messages, cb_state, model_override=model, max_tokens=8192)

    @staticmethod
    def _extract_code_from_text(text: str) -> str:
        """Extract code block from markdown-style response."""
        import re
        match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
