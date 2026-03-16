"""AgentOS Knowledge MCP Server — temporal knowledge graph queries."""

import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastmcp import FastMCP

mcp = FastMCP("AgentOS Knowledge")


def _parse_time_range(time_range: str) -> tuple[datetime, datetime] | None:
    """Parse time range string into datetime tuple."""
    now = datetime.now(timezone.utc)
    ranges = {
        "today": timedelta(days=1),
        "this_week": timedelta(weeks=1),
        "this_month": timedelta(days=30),
        "this_year": timedelta(days=365),
    }
    delta = ranges.get(time_range)
    if delta:
        return (now - delta, now)
    return None


@mcp.tool()
def query_knowledge(query: str, time_range: str = "all") -> str:
    """Query the temporal knowledge graph (Graphiti + Neo4j).

    Args:
        query: Natural language query about facts and relationships.
        time_range: Filter by time — "today", "this_week", "this_month", "all".

    Returns:
        Matching facts with timestamps.
    """
    from memory.graphiti_layer import graphiti

    tr = _parse_time_range(time_range)
    facts = asyncio.run(graphiti.query_facts(query, time_range=tr, limit=10))

    if not facts:
        return "No matching facts found in knowledge graph."

    lines = []
    for f in facts:
        date_str = f.event_time.strftime("%Y-%m-%d")
        lines.append(f"- {f.triple} [{date_str}]")

    return "\n".join(lines)


@mcp.tool()
def add_fact(subject: str, predicate: str, obj: str) -> str:
    """Add a fact to the temporal knowledge graph with automatic timestamp.

    Args:
        subject: The subject entity (e.g., "Tesla").
        predicate: The relationship (e.g., "has_ceo").
        obj: The object entity (e.g., "Elon Musk").

    Returns:
        Confirmation with the stored fact triple.
    """
    from memory.graphiti_layer import graphiti

    fact = asyncio.run(graphiti.add_fact(
        subject=subject,
        predicate=predicate,
        obj=obj,
        source="mcp_tool",
    ))

    return f"Stored: {fact.triple} at {fact.event_time.strftime('%Y-%m-%d %H:%M')}"


@mcp.tool()
def get_entity_timeline(entity: str) -> str:
    """Get chronological timeline of facts about an entity.

    Args:
        entity: The entity name to look up.

    Returns:
        Chronological list of facts about the entity.
    """
    from memory.graphiti_layer import graphiti

    facts = asyncio.run(graphiti.get_timeline(entity))

    if not facts:
        return f"No facts found for entity '{entity}'."

    lines = []
    for f in facts:
        date_str = f.event_time.strftime("%Y-%m-%d")
        lines.append(f"[{date_str}] {f.triple}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
