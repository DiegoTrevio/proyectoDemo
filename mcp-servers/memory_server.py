"""AgentOS Memory MCP Server — search and manage agent memory."""

import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastmcp import FastMCP

mcp = FastMCP("AgentOS Memory")


@mcp.tool()
def search_memory(query: str, user_id: str = "default") -> str:
    """Search across all memory layers (OpenViking + Supermemory + Mem0 fallback).

    Returns relevant context with appropriate detail level.
    Supermemory is the primary memory provider; Mem0 is used as fallback.
    """
    results = []

    # OpenViking search (L0 first, escalate if needed)
    try:
        from memory.openviking_layer import openviking
        ov_results = openviking.search(query, tier=0, limit=5)
        for r in ov_results:
            results.append(f"[{r['path']}] {r['content']}")

        # If top result found, get L1 detail
        if ov_results:
            l1 = openviking.retrieve(ov_results[0]["path"], tier=1)
            if l1 and len(l1) > len(ov_results[0]["content"]):
                results[0] = f"[{ov_results[0]['path']}] {l1}"
    except Exception as e:
        results.append(f"[OpenViking error: {e}]")

    # Supermemory search (primary L1)
    supermemory_found = False
    try:
        from memory.supermemory_layer import supermemory_client
        if supermemory_client.available:
            memories = supermemory_client.search_memory(user_id, query, limit=5)
            for m in memories:
                results.append(f"[supermemory:{m.level}] {m.content}")
            if memories:
                supermemory_found = True
    except Exception as e:
        results.append(f"[Supermemory error: {e}]")

    # Mem0 fallback (only if Supermemory unavailable)
    if not supermemory_found:
        try:
            from memory.mem0_layer import mem0
            memories = mem0.search_memory(user_id, query, limit=3)
            for m in memories:
                results.append(f"[mem0:{m.level}] {m.content}")
        except Exception as e:
            results.append(f"[Mem0 error: {e}]")

    return "\n\n".join(results) if results else "No relevant memories found."


@mcp.tool()
def add_memory(content: str, user_id: str = "default", category: str = "general") -> str:
    """Store a memory entry in Supermemory (primary) and OpenViking (context).

    Supermemory auto-extracts facts, resolves contradictions, and handles
    temporal auto-forgetting. Falls back to Mem0 if Supermemory unavailable.

    Args:
        content: The memory content to store.
        user_id: User identifier.
        category: Category for organization (general, preference, learning).
    """
    stored = []

    # Primary: Supermemory
    try:
        from memory.supermemory_layer import supermemory_client
        if supermemory_client.available:
            entry_id = supermemory_client.add_memory(user_id, content, metadata={"category": category})
            if entry_id:
                stored.append(f"Supermemory: {entry_id}")
    except Exception as e:
        stored.append(f"Supermemory error: {e}")

    # Fallback: Mem0
    if not any("Supermemory:" in s for s in stored):
        try:
            from memory.mem0_layer import mem0
            mem_id = mem0.add_memory(user_id, content, metadata={"category": category})
            if mem_id:
                stored.append(f"Mem0: {mem_id}")
        except Exception as e:
            stored.append(f"Mem0 error: {e}")

    # Always store in OpenViking for local context
    try:
        from memory.openviking_layer import openviking
        path = openviking.store_user_memory(user_id, category, content)
        stored.append(f"OpenViking: {path}")
    except Exception as e:
        stored.append(f"OpenViking error: {e}")

    return f"Stored in: {', '.join(stored)}" if stored else "Failed to store memory."


@mcp.tool()
def get_user_profile(user_id: str = "default") -> str:
    """Get user profile with static facts and dynamic recent context.

    Supermemory builds profiles automatically from stored memories.
    Returns stable facts (e.g. "Senior engineer") and recent activity.
    Falls back to Mem0 get_all if Supermemory unavailable.
    """
    # Primary: Supermemory profile (~50ms)
    try:
        from memory.supermemory_layer import supermemory_client
        if supermemory_client.available:
            profile = supermemory_client.get_profile(user_id)
            parts = []
            if profile.static:
                parts.append("Facts:\n" + "\n".join(f"- {f}" for f in profile.static))
            if profile.dynamic:
                parts.append("Recent activity:\n" + "\n".join(f"- {d}" for d in profile.dynamic))
            if parts:
                return "\n\n".join(parts)
            return "No profile data yet for this user."
    except Exception as e:
        pass  # Fall through to Mem0

    # Fallback: Mem0 get_all
    try:
        from memory.mem0_layer import mem0
        memories = mem0.get_all(user_id)
        if memories:
            return "\n".join(f"- {m.content}" for m in memories)
        return "No preferences stored for this user."
    except Exception as e:
        return f"Error retrieving preferences: {e}"


@mcp.tool()
def get_user_preferences(user_id: str = "default") -> str:
    """Retrieve user preferences (alias for get_user_profile for backward compat)."""
    return get_user_profile(user_id)


if __name__ == "__main__":
    mcp.run()
