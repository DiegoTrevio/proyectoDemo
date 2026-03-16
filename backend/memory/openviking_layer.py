"""OpenViking context DB layer — unified context with L0/L1/L2 token tiers.

Provides a filesystem-like context database using the viking:// paradigm:
  viking://resources/     — documents and source materials
  viking://user/memories/ — user preferences and history
  viking://agent/memories/ — agent knowledge and learnings

Token tiers:
  L0 (~100 tokens):  quick abstract / summary
  L1 (~2K tokens):   overview with key details
  L2 (full):         complete content, loaded only when needed
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("agentos.memory.openviking")


@dataclass
class ContextEntry:
    """A single entry in the context DB."""
    path: str           # viking:// path
    l0: str             # ~100 token abstract
    l1: str             # ~2K token overview
    l2: str             # full content
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def get_tier(self, tier: int) -> str:
        """Get content at the specified tier level."""
        if tier == 0:
            return self.l0
        elif tier == 1:
            return self.l1
        return self.l2

    @property
    def token_estimate(self) -> dict:
        """Rough token estimates per tier."""
        return {
            "l0": len(self.l0) // 4,
            "l1": len(self.l1) // 4,
            "l2": len(self.l2) // 4,
        }


class OpenVikingLayer:
    """Unified context DB with tiered token optimization.

    Falls back to in-memory store if OpenViking SDK is not available.
    """

    def __init__(self):
        self._client = None
        self._fallback_store: dict[str, ContextEntry] = {}

        try:
            import openviking
            self._client = openviking
            logger.info("OpenViking SDK initialized")
        except ImportError:
            logger.info("OpenViking not installed — using in-memory fallback")

    @property
    def available(self) -> bool:
        return self._client is not None

    def store(
        self,
        path: str,
        content: str,
        metadata: dict | None = None,
        l0_summary: str = "",
        l1_overview: str = "",
    ) -> str:
        """Store content at a viking:// path with tiered summaries.

        Args:
            path: viking:// path (e.g. "viking://resources/report-q4")
            content: Full content (L2)
            metadata: Optional metadata dict
            l0_summary: Short abstract (~100 tokens). Auto-generated if empty.
            l1_overview: Overview (~2K tokens). Auto-generated if empty.

        Returns:
            The storage path.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Auto-generate tier summaries if not provided
        if not l0_summary:
            l0_summary = self._generate_l0(content)
        if not l1_overview:
            l1_overview = self._generate_l1(content)

        entry = ContextEntry(
            path=path,
            l0=l0_summary,
            l1=l1_overview,
            l2=content,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

        self._fallback_store[path] = entry
        logger.debug("Stored at %s (L0: %d, L1: %d, L2: %d tokens)",
                     path, *entry.token_estimate.values())
        return path

    def retrieve(self, path: str, tier: int = 0) -> str | None:
        """Retrieve content at a specific tier.

        Args:
            path: viking:// path
            tier: 0 (abstract), 1 (overview), or 2 (full)

        Returns:
            Content string or None if not found.
        """
        entry = self._fallback_store.get(path)
        if entry is None:
            return None
        return entry.get_tier(tier)

    def search(self, query: str, prefix: str = "viking://", tier: int = 0, limit: int = 5) -> list[dict]:
        """Search for relevant entries.

        Args:
            query: Search query.
            prefix: Path prefix to search under.
            tier: Content tier to return.
            limit: Max results.

        Returns:
            List of {path, content, metadata} dicts.
        """
        query_lower = query.lower()
        results = []

        for path, entry in self._fallback_store.items():
            if not path.startswith(prefix):
                continue

            # Simple relevance scoring
            score = 0.0
            if query_lower in entry.l0.lower():
                score += 1.0
            if query_lower in entry.l1.lower():
                score += 0.5
            # Check metadata
            for v in entry.metadata.values():
                if isinstance(v, str) and query_lower in v.lower():
                    score += 0.3

            if score > 0:
                results.append({
                    "path": path,
                    "content": entry.get_tier(tier),
                    "metadata": entry.metadata,
                    "score": score,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def list_paths(self, prefix: str = "viking://") -> list[str]:
        """List all paths under a prefix."""
        return [p for p in self._fallback_store if p.startswith(prefix)]

    def delete(self, path: str) -> bool:
        """Delete an entry."""
        if path in self._fallback_store:
            del self._fallback_store[path]
            return True
        return False

    # ── Resource helpers ──────────────────────────────────────────────────

    def store_resource(self, name: str, content: str, metadata: dict | None = None) -> str:
        """Store a document/source at viking://resources/."""
        path = f"viking://resources/{self._slugify(name)}"
        return self.store(path, content, metadata)

    def store_user_memory(self, user_id: str, key: str, content: str, metadata: dict | None = None) -> str:
        """Store a user preference/memory at viking://user/memories/."""
        path = f"viking://user/memories/{user_id}/{self._slugify(key)}"
        return self.store(path, content, metadata)

    def store_agent_memory(self, agent_name: str, key: str, content: str, metadata: dict | None = None) -> str:
        """Store agent knowledge at viking://agent/memories/."""
        path = f"viking://agent/memories/{agent_name}/{self._slugify(key)}"
        return self.store(path, content, metadata)

    def get_context_for_task(self, query: str, user_id: str = "", max_tokens: int = 500) -> str:
        """Build optimized context string for a task.

        Starts with L0 summaries, escalates to L1/L2 as budget allows.
        """
        parts = []
        token_budget = max_tokens

        # Search across all namespaces
        results = self.search(query, tier=0, limit=10)

        for result in results:
            content = result["content"]
            est_tokens = len(content) // 4

            if est_tokens <= token_budget:
                parts.append(f"[{result['path']}] {content}")
                token_budget -= est_tokens
            else:
                break

        # If we have budget left, try L1 for top results
        if token_budget > 200 and results:
            top_path = results[0]["path"]
            l1_content = self.retrieve(top_path, tier=1)
            if l1_content:
                l1_tokens = len(l1_content) // 4
                if l1_tokens <= token_budget:
                    parts[0] = f"[{top_path}] {l1_content}"

        return "\n\n".join(parts) if parts else ""

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _generate_l0(content: str) -> str:
        """Generate ~100 token abstract from content."""
        # Take first ~400 chars (roughly 100 tokens)
        text = content.strip()
        if len(text) <= 400:
            return text
        # Try to cut at sentence boundary
        cutoff = text[:400]
        last_period = cutoff.rfind(".")
        if last_period > 200:
            return cutoff[:last_period + 1]
        return cutoff + "..."

    @staticmethod
    def _generate_l1(content: str) -> str:
        """Generate ~2K token overview from content."""
        # Take first ~8000 chars (roughly 2K tokens)
        text = content.strip()
        if len(text) <= 8000:
            return text
        cutoff = text[:8000]
        last_period = cutoff.rfind(".")
        if last_period > 4000:
            return cutoff[:last_period + 1]
        return cutoff + "..."

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert a name to a URL-safe slug."""
        slug = name.lower().strip()
        slug = slug.replace(" ", "-")
        # Keep only alphanumeric, hyphens, underscores
        slug = "".join(c for c in slug if c.isalnum() or c in "-_")
        return slug or hashlib.md5(name.encode()).hexdigest()[:8]


# Singleton
openviking = OpenVikingLayer()
