"""Mem0 memory layer for AgentOS.

Provides long-term memory storage and retrieval for agents.
Falls back to a no-op if Mem0 is not configured.
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

    def add_memory(self, user_id: str, content: str, metadata: dict | None = None) -> str | None:
        """Store a memory entry. Returns the memory ID or None."""
        if not self._client:
            logger.debug("Mem0 not available, skipping add_memory")
            return None

        try:
            result = self._client.add(
                content,
                user_id=user_id,
                metadata=metadata or {},
            )
            # Mem0 returns a list of memories
            if result and isinstance(result, list) and len(result) > 0:
                return result[0].get("id", "")
            return ""
        except Exception as e:
            logger.error("Mem0 add_memory failed: %s", e)
            return None

    def search_memory(self, user_id: str, query: str, limit: int = 5) -> list[Memory]:
        """Search for relevant memories. Returns empty list if unavailable."""
        if not self._client:
            return []

        try:
            results = self._client.search(query, user_id=user_id, limit=limit)
            memories = []
            for r in results.get("results", results) if isinstance(results, dict) else results:
                memories.append(Memory(
                    id=r.get("id", ""),
                    content=r.get("memory", r.get("content", "")),
                    metadata=r.get("metadata", {}),
                    score=r.get("score", 0.0),
                ))
            return memories
        except Exception as e:
            logger.error("Mem0 search_memory failed: %s", e)
            return []

    def get_all(self, user_id: str) -> list[Memory]:
        """Get all memories for a user."""
        if not self._client:
            return []

        try:
            results = self._client.get_all(user_id=user_id)
            return [
                Memory(
                    id=r.get("id", ""),
                    content=r.get("memory", r.get("content", "")),
                    metadata=r.get("metadata", {}),
                )
                for r in (results.get("results", results) if isinstance(results, dict) else results)
            ]
        except Exception as e:
            logger.error("Mem0 get_all failed: %s", e)
            return []


# Singleton instance
mem0 = Mem0Layer()
