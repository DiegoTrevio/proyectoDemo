"""Mem0 memory layer for AgentOS — personalized recollection.

Provides 3 levels of memory:
  - User memory: preferences, history, personal context
  - Session memory: within-session learnings and decisions
  - Agent memory: agent-specific knowledge and patterns

Auto-extracts relevant information from conversations.
"""

import logging
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger("agentos.memory")


@dataclass
class Memory:
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0
    level: str = "user"  # user, session, agent


class Mem0Layer:
    """Wrapper around the Mem0 SDK for agent memory operations."""

    def __init__(self):
        self._client = None
        if settings.mem0_api_key:
            try:
                from mem0 import MemoryClient
                self._client = MemoryClient(api_key=settings.mem0_api_key)
                logger.info("Mem0 client initialized")
            except Exception as e:
                logger.warning("Failed to initialize Mem0: %s", e)

    @property
    def available(self) -> bool:
        return self._client is not None

    # ── User memory ───────────────────────────────────────────────────────

    def add_memory(self, user_id: str, content: str, metadata: dict | None = None) -> str | None:
        """Store a user-level memory entry. Returns the memory ID or None."""
        return self._add("user", user_id, content, metadata)

    def search_memory(self, user_id: str, query: str, limit: int = 5) -> list[Memory]:
        """Search user memories."""
        return self._search("user", user_id, query, limit)

    def get_all(self, user_id: str) -> list[Memory]:
        """Get all memories for a user."""
        return self._get_all("user", user_id)

    # ── Session memory ────────────────────────────────────────────────────

    def add_session_memory(self, session_id: str, content: str, metadata: dict | None = None) -> str | None:
        """Store a session-level memory (decisions, findings within a session)."""
        meta = {"level": "session", **(metadata or {})}
        return self._add("session", session_id, content, meta)

    def search_session_memory(self, session_id: str, query: str, limit: int = 5) -> list[Memory]:
        """Search session memories."""
        return self._search("session", session_id, query, limit)

    # ── Agent memory ──────────────────────────────────────────────────────

    def add_agent_memory(self, agent_name: str, content: str, metadata: dict | None = None) -> str | None:
        """Store an agent-level memory (patterns, learnings, capabilities)."""
        meta = {"level": "agent", **(metadata or {})}
        return self._add("agent", f"agent:{agent_name}", content, meta)

    def search_agent_memory(self, agent_name: str, query: str, limit: int = 5) -> list[Memory]:
        """Search agent memories."""
        return self._search("agent", f"agent:{agent_name}", query, limit)

    # ── Auto-extraction ───────────────────────────────────────────────────

    def extract_and_store(
        self,
        user_id: str,
        conversation: list[dict],
        session_id: str = "",
    ) -> list[str]:
        """Auto-extract and store relevant information from a conversation.

        Mem0 natively handles extraction — we pass the conversation directly.

        Args:
            user_id: User identifier.
            conversation: List of message dicts [{role, content}].
            session_id: Optional session ID for session-level memories.

        Returns:
            List of stored memory IDs.
        """
        if not self._client:
            return []

        ids = []
        try:
            result = self._client.add(
                conversation,
                user_id=user_id,
                metadata={"session_id": session_id} if session_id else {},
            )
            if result and isinstance(result, list):
                ids = [r.get("id", "") for r in result if r.get("id")]
                logger.info("Extracted %d memories from conversation", len(ids))
        except Exception as e:
            logger.error("Memory extraction failed: %s", e)

        return ids

    # ── Internal helpers ──────────────────────────────────────────────────

    def _add(self, level: str, user_id: str, content: str, metadata: dict | None = None) -> str | None:
        if not self._client:
            logger.debug("Mem0 not available, skipping add_memory")
            return None

        try:
            meta = {"level": level, **(metadata or {})}
            result = self._client.add(content, user_id=user_id, metadata=meta)
            if result and isinstance(result, list) and len(result) > 0:
                return result[0].get("id", "")
            return ""
        except Exception as e:
            logger.error("Mem0 add_memory failed: %s", e)
            return None

    def _search(self, level: str, user_id: str, query: str, limit: int = 5) -> list[Memory]:
        if not self._client:
            return []

        try:
            results = self._client.search(query, user_id=user_id, limit=limit)
            memories = []
            raw = results.get("results", results) if isinstance(results, dict) else results
            for r in raw:
                memories.append(Memory(
                    id=r.get("id", ""),
                    content=r.get("memory", r.get("content", "")),
                    metadata=r.get("metadata", {}),
                    score=r.get("score", 0.0),
                    level=level,
                ))
            return memories
        except Exception as e:
            logger.error("Mem0 search_memory failed: %s", e)
            return []

    def _get_all(self, level: str, user_id: str) -> list[Memory]:
        if not self._client:
            return []

        try:
            results = self._client.get_all(user_id=user_id)
            raw = results.get("results", results) if isinstance(results, dict) else results
            return [
                Memory(
                    id=r.get("id", ""),
                    content=r.get("memory", r.get("content", "")),
                    metadata=r.get("metadata", {}),
                    level=level,
                )
                for r in raw
            ]
        except Exception as e:
            logger.error("Mem0 get_all failed: %s", e)
            return []


# Singleton instance
mem0 = Mem0Layer()
