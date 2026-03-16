"""AgentOS Memory MCP Server — search and manage agent memory."""

import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastmcp import FastMCP

mcp = FastMCP("AgentOS Memory")


@mcp.tool()
def search_memory(query: str, user_id: str = "default") -> str:
    """Search across all memory layers (OpenViking L0→L1→L2 + Mem0).

    Returns relevant context with appropriate detail level.
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

    # Mem0 search
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
    """Store a memory entry in Mem0 (preferences) and OpenViking (context).

    Args:
        content: The memory content to store.
        user_id: User identifier.
        category: Category for organization (general, preference, learning).
    """
    stored = []

    try:
        from memory.mem0_layer import mem0
        mem_id = mem0.add_memory(user_id, content, metadata={"category": category})
        if mem_id:
            stored.append(f"Mem0: {mem_id}")
    except Exception as e:
        stored.append(f"Mem0 error: {e}")

    try:
        from memory.openviking_layer import openviking
        path = openviking.store_user_memory(user_id, category, content)
        stored.append(f"OpenViking: {path}")
    except Exception as e:
        stored.append(f"OpenViking error: {e}")

    return f"Stored in: {', '.join(stored)}" if stored else "Failed to store memory."


@mcp.tool()
def get_user_preferences(user_id: str = "default") -> str:
    """Retrieve user preferences from Mem0.

    Returns all stored preferences for the user.
    """
    try:
        from memory.mem0_layer import mem0
        memories = mem0.get_all(user_id)
        if memories:
            return "\n".join(f"- {m.content}" for m in memories)
        return "No preferences stored for this user."
    except Exception as e:
        return f"Error retrieving preferences: {e}"


if __name__ == "__main__":
    mcp.run()
