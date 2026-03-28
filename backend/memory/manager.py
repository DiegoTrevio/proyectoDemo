"""Memory Manager — orchestrates the 5-layer memory system.

Integration flow:
  BEFORE execution:
    1. OpenViking L0 for quick context (~100 tokens)
    2. Supermemory for user preferences, history, and hybrid search (replaces Mem0)
    3. Graphiti for timestamped facts
    4. Supermemory user profile for instant personalization (~50ms)
    5. If more detail needed: escalate to L1/L2
  AFTER execution:
    Save new learnings to all layers

Supermemory (supermemory.ai) replaces Mem0 as L1 because:
  - #1 on LongMemEval, LoCoMo, and ConvoMem benchmarks
  - Automatic contradiction resolution and temporal auto-forgetting
  - User profiles with static facts + dynamic context
  - Connectors for Google Drive, Gmail, Notion, GitHub
  - Multimodal processing (PDF, images/OCR, video, code/AST)

Mem0 is kept as a fallback if Supermemory is not configured.
"""

import logging
from datetime import datetime, timezone

from memory.graphiti_layer import Fact, graphiti
from memory.mem0_layer import Memory, mem0
from memory.openviking_layer import openviking
from memory.project_context import project_context
from memory.supermemory_layer import supermemory_client

logger = logging.getLogger("agentos.memory.manager")


async def gather_context(
    goal: str,
    user_id: str = "default",
    task_id: str = "",
    max_tokens: int = 1000,
) -> dict:
    """Gather context from all memory layers before task execution.

    Returns a dict with context from each layer, optimized for token budget.
    """
    context = {
        "openviking": "",
        "project_context": "",
        "supermemory_memories": [],
        "mem0_memories": [],  # Kept for backward compat (empty if Supermemory active)
        "graphiti_facts": [],
        "user_profile": {"static": [], "dynamic": []},
        "combined": "",
    }

    parts = []
    token_budget = max_tokens

    # ── Layer 0.5: Project Context (structured project knowledge) ─────
    try:
        pc = project_context.get_context_for_task(goal, max_tokens=min(300, token_budget))
        if pc:
            context["project_context"] = pc
            parts.append(f"[Project Context]\n{pc}")
            token_budget -= len(pc) // 4
    except Exception as e:
        logger.warning("Project context retrieval failed: %s", e)

    # ── Layer 0: OpenViking L0 (quick context) ────────────────────────
    try:
        ov_context = openviking.get_context_for_task(goal, user_id=user_id, max_tokens=min(300, token_budget))
        if ov_context:
            context["openviking"] = ov_context
            parts.append(f"[Context]\n{ov_context}")
            token_budget -= len(ov_context) // 4
    except Exception as e:
        logger.warning("OpenViking context retrieval failed: %s", e)

    # ── Layer 1: Supermemory (replaces Mem0 — user preferences + history) ──
    memories_found = False
    if supermemory_client.available:
        try:
            memories = await supermemory_client.async_search_memory(user_id, goal, limit=5)
            if memories:
                memories_found = True
                context["supermemory_memories"] = [{"content": m.content, "score": m.score} for m in memories]
                # Also populate mem0_memories for backward compat
                context["mem0_memories"] = context["supermemory_memories"]
                mem_text = "\n".join(f"- {m.content}" for m in memories)
                parts.append(f"[Prior Knowledge]\n{mem_text}")
                token_budget -= len(mem_text) // 4
        except Exception as e:
            logger.warning("Supermemory search failed, falling back to Mem0: %s", e)

    # Fallback to Mem0 if Supermemory unavailable or returned nothing
    if not memories_found:
        try:
            mem0_results = mem0.search_memory(user_id, goal, limit=3)
            if mem0_results:
                context["mem0_memories"] = [{"content": m.content, "score": m.score} for m in mem0_results]
                mem_text = "\n".join(f"- {m.content}" for m in mem0_results)
                parts.append(f"[Prior Knowledge]\n{mem_text}")
                token_budget -= len(mem_text) // 4
        except Exception as e:
            logger.warning("Mem0 search failed: %s", e)

    # ── Layer 2: Graphiti (timestamped facts) ─────────────────────────
    try:
        facts = await graphiti.query_facts(goal, limit=5)
        if facts:
            context["graphiti_facts"] = [
                {
                    "subject": f.subject,
                    "predicate": f.predicate,
                    "object": f.object,
                    "event_time": f.event_time.isoformat(),
                }
                for f in facts
            ]
            fact_text = "\n".join(f"- {f.triple} ({f.event_time.strftime('%Y-%m-%d')})" for f in facts)
            parts.append(f"[Known Facts]\n{fact_text}")
    except Exception as e:
        logger.warning("Graphiti query failed: %s", e)

    # ── Layer 4: Supermemory user profile (instant personalization) ───
    if supermemory_client.available and token_budget > 100:
        try:
            profile = await supermemory_client.async_get_profile(user_id, query=goal)
            context["user_profile"] = {
                "static": profile.static,
                "dynamic": profile.dynamic,
            }
            profile_parts = []
            if profile.static:
                profile_parts.append("Facts: " + "; ".join(profile.static[:5]))
            if profile.dynamic:
                profile_parts.append("Recent: " + "; ".join(profile.dynamic[:3]))
            if profile_parts:
                parts.insert(0, f"[User Profile]\n{chr(10).join(profile_parts)}")
        except Exception as e:
            logger.warning("Supermemory profile retrieval failed: %s", e)

    context["combined"] = "\n\n".join(parts) if parts else ""
    return context


async def save_learnings(
    goal: str,
    result: str,
    task_id: str = "",
    user_id: str = "default",
    agent_name: str = "orchestrator",
    facts: list[dict] | None = None,
) -> dict:
    """Save new learnings to all 4 memory layers after task execution.

    Args:
        goal: The original task goal.
        result: The task result/output.
        task_id: Task identifier for tracing.
        user_id: User identifier.
        agent_name: Agent that produced the result.
        facts: Optional list of extracted facts [{subject, predicate, object}].

    Returns:
        Dict with save status per layer.
    """
    status = {"openviking": False, "project_context": False, "supermemory": False, "mem0": False, "graphiti": False, "redis": False}
    now = datetime.now(timezone.utc)

    # ── Layer 0: OpenViking — store as resource ───────────────────────
    try:
        summary = f"Task: {goal}\nResult: {result[:2000]}"
        openviking.store_resource(
            name=f"task-{task_id or 'unknown'}",
            content=summary,
            metadata={
                "task_id": task_id,
                "user_id": user_id,
                "agent": agent_name,
                "timestamp": now.isoformat(),
            },
        )
        # Also store as agent memory
        openviking.store_agent_memory(
            agent_name=agent_name,
            key=f"task-{task_id}",
            content=f"Completed: {goal[:200]} -> {result[:500]}",
        )
        status["openviking"] = True
    except Exception as e:
        logger.warning("OpenViking save failed: %s", e)

    # ── Layer 0.5: Project Context — update decisions if facts provided ──
    if facts:
        decision_facts = [f for f in facts if f.get("predicate") in ("decided", "chose", "adopted", "deprecated")]
        if decision_facts:
            try:
                existing = project_context.get_section("decisions", tier=2) or ""
                new_entries = "\n".join(
                    f"- {f['subject']} {f['predicate']} {f.get('object', '')}" for f in decision_facts
                )
                project_context.store_section("decisions", f"{existing}\n{new_entries}".strip())
                status["project_context"] = True
            except Exception as e:
                logger.warning("Project context decisions update failed: %s", e)

    # ── Layer 1: Supermemory — primary user/agent memory ──────────────
    if supermemory_client.available:
        try:
            supermemory_client.add_memory(
                user_id=user_id,
                content=f"Researched/completed: {goal}. Key finding: {result[:500]}",
                metadata={"task_id": task_id, "agent": agent_name},
            )
            supermemory_client.add_agent_memory(
                agent_name=agent_name,
                content=f"Successfully handled task: {goal[:200]}",
                metadata={"task_id": task_id},
            )
            status["supermemory"] = True
        except Exception as e:
            logger.warning("Supermemory save failed: %s", e)

    # ── Layer 1 fallback: Mem0 — if Supermemory not configured ────────
    if not status["supermemory"]:
        try:
            mem0.add_memory(
                user_id=user_id,
                content=f"Researched/completed: {goal}. Key finding: {result[:500]}",
                metadata={"task_id": task_id, "agent": agent_name},
            )
            mem0.add_agent_memory(
                agent_name=agent_name,
                content=f"Successfully handled task: {goal[:200]}",
                metadata={"task_id": task_id},
            )
            status["mem0"] = True
        except Exception as e:
            logger.warning("Mem0 save failed: %s", e)

    # ── Layer 3: Graphiti — store facts with timestamps ───────────────
    try:
        # Store the task completion fact
        await graphiti.add_fact(
            subject=user_id,
            predicate="completed_task",
            obj=goal[:200],
            event_time=now,
            source=task_id,
        )

        # Store additional extracted facts
        if facts:
            for fact_data in facts:
                await graphiti.add_fact(
                    subject=fact_data.get("subject", ""),
                    predicate=fact_data.get("predicate", "related_to"),
                    obj=fact_data.get("object", ""),
                    event_time=now,
                    source=task_id,
                    metadata=fact_data.get("metadata", {}),
                )

        status["graphiti"] = True
    except Exception as e:
        logger.warning("Graphiti save failed: %s", e)

    # ── Layer 4: Redis — update session state (handled by redis_session module) ──
    try:
        from memory.redis_session import set_task_state
        await set_task_state(task_id, {
            "goal": goal,
            "status": "completed",
            "result_preview": result[:500],
            "agent": agent_name,
            "completed_at": now.isoformat(),
        })
        status["redis"] = True
    except Exception as e:
        logger.warning("Redis session save failed: %s", e)

    logger.info("Saved learnings for task %s: %s", task_id, status)
    return status


def get_memory_stats() -> dict:
    """Get statistics across all memory layers."""
    # Project context drift check
    drift = project_context.check_drift()

    return {
        "openviking": {
            "available": openviking.available,
            "entries": len(openviking._fallback_store),
            "namespaces": {
                "resources": len(openviking.list_paths("viking://resources/")),
                "user_memories": len(openviking.list_paths("viking://user/memories/")),
                "agent_memories": len(openviking.list_paths("viking://agent/memories/")),
            },
        },
        "project_context": {
            "sections": list(project_context.get_all_sections(tier=0).keys()),
            "drift_score": drift.score,
            "drift_healthy": drift.healthy,
            "drift_issues": len(drift.issues),
        },
        "supermemory": {
            "available": supermemory_client.available,
            "provider": "supermemory.ai",
            "role": "L1 primary (replaces Mem0)",
        },
        "mem0": {
            "available": mem0.available,
            "role": "L1 fallback (used when Supermemory unavailable)",
        },
        "graphiti": graphiti.get_stats(),
    }
