"""Supermemory layer for AgentOS — replaces Mem0 as L1 memory provider.

Supermemory (supermemory.ai) provides:
  - Automatic fact extraction from conversations
  - Contradiction resolution and temporal auto-forgetting
  - User profiles (static facts + dynamic recent context) in ~50ms
  - Hybrid search (RAG + memory) in a single query
  - Connectors for Google Drive, Gmail, Notion, GitHub
  - Multimodal processing (PDF, images/OCR, video, code/AST)

Uses container_tags to scope memory per user/agent/session.

API reference: https://docs.supermemory.ai/sdks/python
"""

import logging
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger("agentos.memory.supermemory")


@dataclass
class SupermemoryEntry:
    """A memory entry from Supermemory."""
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0
    level: str = "user"  # user, session, agent


@dataclass
class UserProfile:
    """User profile with static facts and dynamic recent context."""
    static: list[str] = field(default_factory=list)
    dynamic: list[str] = field(default_factory=list)


class SupermemoryLayer:
    """Wrapper around the Supermemory Python SDK.

    Provides the same interface as Mem0Layer for drop-in replacement,
    plus additional features: profiles, contradiction resolution, connectors.

    Usage:
        from memory.supermemory_layer import supermemory_client
        supermemory_client.add_memory("user_123", "Prefers dark mode")
        results = supermemory_client.search_memory("user_123", "UI preferences")
        profile = supermemory_client.get_profile("user_123")
    """

    def __init__(self):
        self._client = None
        self._async_client = None
        if settings.supermemory_api_key:
            try:
                from supermemory import Supermemory
                self._client = Supermemory(api_key=settings.supermemory_api_key)
                logger.info("Supermemory sync client initialized")
            except Exception as e:
                logger.warning("Failed to initialize Supermemory: %s", e)

    def _get_async_client(self):
        """Lazy-init async client (only when needed)."""
        if self._async_client is None and settings.supermemory_api_key:
            try:
                from supermemory import AsyncSupermemory
                self._async_client = AsyncSupermemory(api_key=settings.supermemory_api_key)
                logger.info("Supermemory async client initialized")
            except Exception as e:
                logger.warning("Failed to initialize async Supermemory: %s", e)
        return self._async_client

    @property
    def available(self) -> bool:
        return self._client is not None

    # ── Container tag helpers ────────────────────────────────────────────

    @staticmethod
    def _user_tag(user_id: str) -> str:
        return f"user_{user_id}"

    @staticmethod
    def _session_tag(session_id: str) -> str:
        return f"session_{session_id}"

    @staticmethod
    def _agent_tag(agent_name: str) -> str:
        return f"agent_{agent_name}"

    # ── User memory ──────────────────────────────────────────────────────

    def add_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> str | None:
        """Store a user-level memory entry. Returns confirmation or None."""
        if not self._client:
            logger.debug("Supermemory not available, skipping add_memory")
            return None

        try:
            result = self._client.add(
                content=content,
                container_tags=[self._user_tag(user_id)],
                metadata={"level": "user", **(metadata or {})},
            )
            entry_id = getattr(result, "id", None) or str(result)
            logger.debug("Supermemory add_memory: %s", entry_id)
            return entry_id
        except Exception as e:
            logger.error("Supermemory add_memory failed: %s", e)
            return None

    def search_memory(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[SupermemoryEntry]:
        """Search user memories via hybrid search (RAG + memory)."""
        if not self._client:
            return []

        try:
            results = self._client.search.memories(
                q=query,
                container_tags=[self._user_tag(user_id)],
                limit=limit,
            )
            entries = []
            raw = getattr(results, "results", results) if not isinstance(results, list) else results
            for r in raw:
                entries.append(SupermemoryEntry(
                    id=getattr(r, "id", ""),
                    content=getattr(r, "content", getattr(r, "memory", str(r))),
                    metadata=getattr(r, "metadata", {}),
                    score=getattr(r, "score", 0.0),
                    level="user",
                ))
            return entries
        except Exception as e:
            logger.error("Supermemory search_memory failed: %s", e)
            return []

    def get_all(self, user_id: str) -> list[SupermemoryEntry]:
        """Get all memories for a user via document search."""
        if not self._client:
            return []

        try:
            results = self._client.search.documents(
                q="*",
                container_tags=[self._user_tag(user_id)],
                limit=50,
            )
            raw = getattr(results, "results", results) if not isinstance(results, list) else results
            return [
                SupermemoryEntry(
                    id=getattr(r, "id", ""),
                    content=getattr(r, "content", getattr(r, "memory", str(r))),
                    metadata=getattr(r, "metadata", {}),
                    level="user",
                )
                for r in raw
            ]
        except Exception as e:
            logger.error("Supermemory get_all failed: %s", e)
            return []

    # ── User profile (Supermemory exclusive) ─────────────────────────────

    def get_profile(self, user_id: str, query: str = "") -> UserProfile:
        """Get user profile with static facts and dynamic context (~50ms).

        This is a Supermemory-exclusive feature — Mem0 doesn't have this.
        Inject into system prompt for instant personalization.
        """
        if not self._client:
            return UserProfile()

        try:
            kwargs = {"container_tag": self._user_tag(user_id)}
            if query:
                kwargs["q"] = query
            result = self._client.profile(**kwargs)
            profile_data = getattr(result, "profile", result)
            return UserProfile(
                static=list(getattr(profile_data, "static", []) or []),
                dynamic=list(getattr(profile_data, "dynamic", []) or []),
            )
        except Exception as e:
            logger.error("Supermemory get_profile failed: %s", e)
            return UserProfile()

    # ── Session memory ───────────────────────────────────────────────────

    def add_session_memory(
        self,
        session_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> str | None:
        """Store a session-level memory (decisions, findings within a session)."""
        if not self._client:
            return None

        try:
            result = self._client.add(
                content=content,
                container_tags=[self._session_tag(session_id)],
                metadata={"level": "session", **(metadata or {})},
            )
            return getattr(result, "id", None) or str(result)
        except Exception as e:
            logger.error("Supermemory add_session_memory failed: %s", e)
            return None

    def search_session_memory(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> list[SupermemoryEntry]:
        """Search session memories."""
        if not self._client:
            return []

        try:
            results = self._client.search.memories(
                q=query,
                container_tags=[self._session_tag(session_id)],
                limit=limit,
            )
            raw = getattr(results, "results", results) if not isinstance(results, list) else results
            return [
                SupermemoryEntry(
                    id=getattr(r, "id", ""),
                    content=getattr(r, "content", getattr(r, "memory", str(r))),
                    metadata=getattr(r, "metadata", {}),
                    score=getattr(r, "score", 0.0),
                    level="session",
                )
                for r in raw
            ]
        except Exception as e:
            logger.error("Supermemory search_session_memory failed: %s", e)
            return []

    # ── Agent memory ─────────────────────────────────────────────────────

    def add_agent_memory(
        self,
        agent_name: str,
        content: str,
        metadata: dict | None = None,
    ) -> str | None:
        """Store an agent-level memory (patterns, learnings, capabilities)."""
        if not self._client:
            return None

        try:
            result = self._client.add(
                content=content,
                container_tags=[self._agent_tag(agent_name)],
                metadata={"level": "agent", **(metadata or {})},
            )
            return getattr(result, "id", None) or str(result)
        except Exception as e:
            logger.error("Supermemory add_agent_memory failed: %s", e)
            return None

    def search_agent_memory(
        self,
        agent_name: str,
        query: str,
        limit: int = 5,
    ) -> list[SupermemoryEntry]:
        """Search agent memories."""
        if not self._client:
            return []

        try:
            results = self._client.search.memories(
                q=query,
                container_tags=[self._agent_tag(agent_name)],
                limit=limit,
            )
            raw = getattr(results, "results", results) if not isinstance(results, list) else results
            return [
                SupermemoryEntry(
                    id=getattr(r, "id", ""),
                    content=getattr(r, "content", getattr(r, "memory", str(r))),
                    metadata=getattr(r, "metadata", {}),
                    score=getattr(r, "score", 0.0),
                    level="agent",
                )
                for r in raw
            ]
        except Exception as e:
            logger.error("Supermemory search_agent_memory failed: %s", e)
            return []

    # ── Auto-extraction ──────────────────────────────────────────────────

    def extract_and_store(
        self,
        user_id: str,
        conversation: list[dict],
        session_id: str = "",
    ) -> list[str]:
        """Auto-extract and store relevant information from a conversation.

        Supermemory natively handles fact extraction, contradiction resolution,
        and temporal auto-forgetting.

        Args:
            user_id: User identifier.
            conversation: List of message dicts [{role, content}].
            session_id: Optional session ID for scoping.

        Returns:
            List of stored entry IDs.
        """
        if not self._client:
            return []

        ids = []
        try:
            # Build a combined conversation text for Supermemory
            conv_text = "\n".join(
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in conversation
            )

            tags = [self._user_tag(user_id)]
            if session_id:
                tags.append(self._session_tag(session_id))

            result = self._client.add(
                content=conv_text,
                container_tags=tags,
                metadata={"source": "conversation", "session_id": session_id},
            )
            entry_id = getattr(result, "id", None) or str(result)
            if entry_id:
                ids.append(entry_id)
                logger.info("Supermemory extracted memories from conversation")
        except Exception as e:
            logger.error("Supermemory extraction failed: %s", e)

        return ids

    # ── Async variants (for memory manager) ──────────────────────────────

    async def async_search_memory(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[SupermemoryEntry]:
        """Async version of search_memory for use in gather_context."""
        client = self._get_async_client()
        if not client:
            # Fallback to sync
            return self.search_memory(user_id, query, limit)

        try:
            results = await client.search.memories(
                q=query,
                container_tags=[self._user_tag(user_id)],
                limit=limit,
            )
            raw = getattr(results, "results", results) if not isinstance(results, list) else results
            return [
                SupermemoryEntry(
                    id=getattr(r, "id", ""),
                    content=getattr(r, "content", getattr(r, "memory", str(r))),
                    metadata=getattr(r, "metadata", {}),
                    score=getattr(r, "score", 0.0),
                    level="user",
                )
                for r in raw
            ]
        except Exception as e:
            logger.error("Supermemory async search failed: %s", e)
            return []

    async def async_get_profile(self, user_id: str, query: str = "") -> UserProfile:
        """Async version of get_profile."""
        client = self._get_async_client()
        if not client:
            return self.get_profile(user_id, query)

        try:
            kwargs = {"container_tag": self._user_tag(user_id)}
            if query:
                kwargs["q"] = query
            result = await client.profile(**kwargs)
            profile_data = getattr(result, "profile", result)
            return UserProfile(
                static=list(getattr(profile_data, "static", []) or []),
                dynamic=list(getattr(profile_data, "dynamic", []) or []),
            )
        except Exception as e:
            logger.error("Supermemory async get_profile failed: %s", e)
            return UserProfile()


# Singleton instance
supermemory_client = SupermemoryLayer()
