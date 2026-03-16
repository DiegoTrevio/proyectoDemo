"""AgentOS Orchestrator — LangGraph-based task orchestration engine.

The Orchestrator is the brain of AgentOS. It receives a user goal and:
1. CLASSIFY — determines task type and complexity
2. PLAN — generates an execution plan with sub-tasks (using extended thinking)
3. EXECUTE — dispatches sub-tasks to specialist agents
4. REFLECT — evaluates results, decides whether to continue or deliver
5. DELIVER — packages the final result
"""

import json
import logging
from datetime import datetime, timezone
from typing import TypedDict

import redis.asyncio as aioredis
from langgraph.graph import END, StateGraph

from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerState
from agents.dispatcher import dispatch
from config.model_router import ORCHESTRATOR, select_model
from config.settings import settings

logger = logging.getLogger("agentos.orchestrator")


# ─── State ────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    task_id: str
    goal: str
    task_type: str          # research, code, browser, document, multi
    complexity: str         # simple, medium, complex
    plan: list[dict]        # [{step, agent, description, status}]
    current_step: int
    results: list[dict]     # [{step, agent, output, artifacts}]
    errors: list[str]       # never cleared — full error history
    memory_context: dict
    iteration: int
    max_iterations: int
    final_output: str
    status: str             # classify, plan, execute, reflect, deliver, done, failed
    cb_state: dict          # serialized CircuitBreakerState


# ─── Prompts (static parts first for KV-cache optimization) ──────────────

_SYSTEM_PROMPT = """You are the AgentOS Orchestrator — the central brain that coordinates AI agents.

## Your Role
You receive a user goal, break it into sub-tasks, assign each to the right specialist agent, and synthesize the final result.

## Available Agents
- researcher: Web search, information gathering, fact-checking
- coder: Write, edit, and debug code
- browser: Navigate websites, fill forms, extract data
- document_writer: Create documents, reports, summaries
- validator: Review, lint, test outputs

## Rules
1. Always decompose complex goals into concrete, actionable steps
2. Each step must specify exactly ONE agent
3. Keep plans minimal — prefer fewer steps over more
4. If a step fails, note the error and adapt the plan
5. Never repeat a failed step more than once with the same approach
6. Respond ONLY with valid JSON — no markdown, no explanation outside JSON
"""

_CLASSIFY_PROMPT = """Classify this user goal. Respond with JSON only:
{{"task_type": "research"|"code"|"browser"|"document"|"multi", "complexity": "simple"|"medium"|"complex", "reasoning": "..."}}

Goal: {goal}"""

_PLAN_PROMPT = """Create an execution plan for this goal. Respond with JSON only:
{{"steps": [{{"step": 1, "agent": "agent_name", "description": "what to do"}}]}}

Goal: {goal}
Task type: {task_type}
Complexity: {complexity}
{context_section}"""

_REFLECT_PROMPT = """Evaluate the execution results and decide the next action.
Respond with JSON only:
{{"decision": "deliver"|"continue"|"retry", "reasoning": "...", "adjustments": []}}

Goal: {goal}
Plan: {plan}
Results so far: {results}
Errors: {errors}
Iteration: {iteration}/{max_iterations}"""


# ─── SSE publishing ──────────────────────────────────────────────────────

async def _publish(task_id: str, event_type: str, content: str, agent: str = "orchestrator"):
    """Publish an SSE event to the task's Redis channel."""
    r = aioredis.from_url(settings.redis_url)
    try:
        payload = json.dumps({
            "type": event_type,
            "content": content,
            "agent": agent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await r.publish(f"task:{task_id}:events", payload)
    finally:
        await r.close()


# ─── LLM call helper (uses LiteLLM via HTTP) ─────────────────────────────

async def _call_orchestrator_llm(messages: list[dict], max_tokens: int = 4096) -> str:
    """Call the orchestrator model via LiteLLM proxy."""
    import httpx

    async with httpx.AsyncClient(base_url="http://litellm:4000", timeout=120) as client:
        resp = await client.post(
            "/chat/completions",
            json={
                "model": ORCHESTRATOR,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LLM call failed: {resp.status_code} {resp.text[:200]}")
        return resp.json()["choices"][0]["message"]["content"]


def _parse_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        # Remove code fences
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


# ─── Graph node functions ─────────────────────────────────────────────────

async def classify_node(state: AgentState) -> dict:
    """CLASSIFY: Determine task type and complexity."""
    task_id = state["task_id"]
    goal = state["goal"]

    await _publish(task_id, "thought", f"Classifying task: {goal[:100]}...")

    try:
        response = await _call_orchestrator_llm([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _CLASSIFY_PROMPT.format(goal=goal)},
        ], max_tokens=256)

        result = _parse_json(response)
        task_type = result.get("task_type", "research")
        complexity = result.get("complexity", "medium")

        # Validate
        valid_types = {"research", "code", "browser", "document", "multi"}
        valid_complexity = {"simple", "medium", "complex"}
        if task_type not in valid_types:
            task_type = "research"
        if complexity not in valid_complexity:
            complexity = "medium"

        await _publish(task_id, "thought",
                       f"Classified as {task_type}/{complexity}: {result.get('reasoning', '')}")

        return {
            "task_type": task_type,
            "complexity": complexity,
            "status": "plan",
        }
    except Exception as e:
        logger.exception("Classification failed")
        await _publish(task_id, "error", f"Classification error: {e}")
        return {
            "task_type": "research",
            "complexity": "simple",
            "errors": state["errors"] + [f"classify: {e}"],
            "status": "plan",
        }


async def plan_node(state: AgentState) -> dict:
    """PLAN: Generate execution plan with sub-tasks."""
    task_id = state["task_id"]
    goal = state["goal"]

    await _publish(task_id, "thought", "Generating execution plan...")

    context_section = ""
    if state["errors"]:
        context_section += f"\nPrevious errors (do NOT repeat these approaches):\n"
        for err in state["errors"]:
            context_section += f"- {err}\n"
    if state["results"]:
        context_section += f"\nPartial results so far:\n"
        for r in state["results"]:
            context_section += f"- Step {r.get('step', '?')}: {r.get('output', '')[:200]}\n"

    try:
        response = await _call_orchestrator_llm([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _PLAN_PROMPT.format(
                goal=goal,
                task_type=state["task_type"],
                complexity=state["complexity"],
                context_section=context_section,
            )},
        ], max_tokens=2048)

        result = _parse_json(response)
        steps = result.get("steps", [])

        plan = []
        for s in steps:
            plan.append({
                "step": s.get("step", len(plan) + 1),
                "agent": s.get("agent", "researcher"),
                "description": s.get("description", ""),
                "status": "pending",
            })

        if not plan:
            plan = [{"step": 1, "agent": "researcher", "description": goal, "status": "pending"}]

        plan_summary = "; ".join(f"Step {p['step']}: {p['agent']} — {p['description'][:60]}" for p in plan)
        await _publish(task_id, "thought", f"Plan ready ({len(plan)} steps): {plan_summary}")

        return {"plan": plan, "current_step": 0, "status": "execute"}
    except Exception as e:
        logger.exception("Planning failed")
        await _publish(task_id, "error", f"Planning error: {e}")
        # Fallback: single-step plan
        fallback_plan = [{"step": 1, "agent": "researcher", "description": goal, "status": "pending"}]
        return {
            "plan": fallback_plan,
            "current_step": 0,
            "errors": state["errors"] + [f"plan: {e}"],
            "status": "execute",
        }


async def execute_node(state: AgentState) -> dict:
    """EXECUTE: Dispatch current step to the assigned agent."""
    task_id = state["task_id"]
    plan = state["plan"]
    current_step = state["current_step"]
    results = list(state["results"])
    errors = list(state["errors"])

    if current_step >= len(plan):
        return {"status": "reflect"}

    step = plan[current_step]
    agent_name = step["agent"]
    description = step["description"]

    await _publish(task_id, "action",
                   f"Executing step {step['step']}: {agent_name} — {description[:80]}",
                   agent=agent_name)

    # Update plan step status
    updated_plan = list(plan)
    updated_plan[current_step] = {**step, "status": "running"}

    try:
        result = await dispatch(
            agent_name=agent_name,
            task={"goal": description, "step_index": current_step, "task_id": task_id},
            context={"memory": state["memory_context"], "prior_results": results},
        )

        updated_plan[current_step] = {**step, "status": "completed" if result.success else "failed"}

        results.append({
            "step": step["step"],
            "agent": agent_name,
            "output": result.output,
            "artifacts": result.artifacts,
            "success": result.success,
        })

        if result.success:
            await _publish(task_id, "result",
                           f"Step {step['step']} completed: {result.output[:200]}",
                           agent=agent_name)
        else:
            error_msg = result.error or "Unknown error"
            errors.append(f"step {step['step']} ({agent_name}): {error_msg}")
            await _publish(task_id, "error",
                           f"Step {step['step']} failed: {error_msg}",
                           agent=agent_name)

    except Exception as e:
        logger.exception("Execute step %d failed", step["step"])
        updated_plan[current_step] = {**step, "status": "failed"}
        errors.append(f"step {step['step']} ({agent_name}): {e}")
        results.append({
            "step": step["step"],
            "agent": agent_name,
            "output": "",
            "artifacts": [],
            "success": False,
        })
        await _publish(task_id, "error", f"Step {step['step']} exception: {e}", agent=agent_name)

    next_step = current_step + 1
    next_status = "execute" if next_step < len(plan) else "reflect"

    return {
        "plan": updated_plan,
        "current_step": next_step,
        "results": results,
        "errors": errors,
        "iteration": state["iteration"] + 1,
        "status": next_status,
    }


async def reflect_node(state: AgentState) -> dict:
    """REFLECT: Evaluate results and decide whether to deliver or continue."""
    task_id = state["task_id"]

    await _publish(task_id, "thought", "Reflecting on results...")

    # Circuit breaker check
    if state["iteration"] >= state["max_iterations"]:
        await _publish(task_id, "thought",
                       f"Max iterations ({state['max_iterations']}) reached — delivering partial results")
        return {"status": "deliver"}

    try:
        response = await _call_orchestrator_llm([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _REFLECT_PROMPT.format(
                goal=state["goal"],
                plan=json.dumps(state["plan"], indent=2),
                results=json.dumps(state["results"], indent=2),
                errors=json.dumps(state["errors"]),
                iteration=state["iteration"],
                max_iterations=state["max_iterations"],
            )},
        ], max_tokens=512)

        result = _parse_json(response)
        decision = result.get("decision", "deliver")
        reasoning = result.get("reasoning", "")

        await _publish(task_id, "thought", f"Reflection: {decision} — {reasoning}")

        if decision == "deliver":
            return {"status": "deliver"}
        elif decision == "continue" or decision == "retry":
            return {"current_step": 0, "status": "plan"}
        else:
            return {"status": "deliver"}
    except Exception as e:
        logger.exception("Reflection failed")
        await _publish(task_id, "error", f"Reflection error: {e}")
        return {
            "errors": state["errors"] + [f"reflect: {e}"],
            "status": "deliver",
        }


async def deliver_node(state: AgentState) -> dict:
    """DELIVER: Package the final result."""
    task_id = state["task_id"]

    # Compile all successful outputs
    outputs = []
    artifacts = []
    for r in state["results"]:
        if r.get("success"):
            outputs.append(r.get("output", ""))
            artifacts.extend(r.get("artifacts", []))

    if outputs:
        final_output = "\n\n".join(outputs)
    elif state["errors"]:
        final_output = f"Task could not be completed. Errors:\n" + "\n".join(state["errors"])
    else:
        final_output = "No results produced."

    await _publish(task_id, "result", final_output)
    await _publish(task_id, "action", "Task completed")

    return {"final_output": final_output, "status": "done"}


# ─── Routing ──────────────────────────────────────────────────────────────

def _route(state: AgentState) -> str:
    """Route to the next node based on state['status']."""
    status = state.get("status", "classify")
    if status == "classify":
        return "classify"
    elif status == "plan":
        return "plan"
    elif status == "execute":
        return "execute"
    elif status == "reflect":
        return "reflect"
    elif status == "deliver":
        return "deliver"
    else:
        return END


# ─── Graph construction ──────────────────────────────────────────────────

def build_orchestrator_graph() -> StateGraph:
    """Build and compile the Orchestrator LangGraph."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("classify", classify_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("deliver", deliver_node)

    # Set entry point
    graph.set_entry_point("classify")

    # Add edges — each node routes to the next based on state["status"]
    graph.add_conditional_edges("classify", _route, {
        "plan": "plan",
        "execute": "execute",
        "deliver": "deliver",
    })
    graph.add_conditional_edges("plan", _route, {
        "execute": "execute",
        "deliver": "deliver",
    })
    graph.add_conditional_edges("execute", _route, {
        "execute": "execute",
        "reflect": "reflect",
        "deliver": "deliver",
    })
    graph.add_conditional_edges("reflect", _route, {
        "plan": "plan",
        "deliver": "deliver",
    })
    graph.add_edge("deliver", END)

    return graph.compile()


# ─── Public API ──────────────────────────────────────────────────────────

_compiled_graph = None


def get_orchestrator():
    """Get or create the compiled orchestrator graph (singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_orchestrator_graph()
    return _compiled_graph


async def run_task(task_id: str, goal: str, config: dict | None = None) -> str:
    """Run the full orchestrator pipeline for a task.

    Args:
        task_id: Unique task identifier.
        goal: The user's goal string.
        config: Optional task configuration overrides.

    Returns:
        The final output string.
    """
    cb_config = CircuitBreakerConfig()
    if config:
        if "max_iterations" in config:
            cb_config.max_iterations = config["max_iterations"]
        if "max_cost" in config:
            cb_config.max_cost_per_task = config["max_cost"]
        if "timeout" in config:
            cb_config.timeout_seconds = config["timeout"]

    initial_state: AgentState = {
        "task_id": task_id,
        "goal": goal,
        "task_type": "",
        "complexity": "",
        "plan": [],
        "current_step": 0,
        "results": [],
        "errors": [],
        "memory_context": {},
        "iteration": 0,
        "max_iterations": cb_config.max_iterations,
        "final_output": "",
        "status": "classify",
        "cb_state": {},
    }

    orchestrator = get_orchestrator()

    try:
        final_state = await orchestrator.ainvoke(initial_state)
        return final_state.get("final_output", "No output produced")
    except Exception as e:
        logger.exception("Orchestrator failed for task %s", task_id)
        await _publish(task_id, "error", f"Orchestrator fatal error: {e}")
        return f"Error: {e}"
