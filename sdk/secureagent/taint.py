"""Taint Tracking — labels external content to prevent untrusted tool calls.

All content from external sources (web scraping, APIs, user documents, search
results) carries a TaintLabel. Tainted content cannot trigger destructive
tool calls without explicit human approval.

Features:
- Full SHA-256 hash with configurable salt (prevents collisions + precomputation)
- Strict mode: unknown content blocked from destructive tools
- Launder audit trail with callback
- Bounded registry with TTL-based eviction
"""

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("secureagent.taint")


class TaintSource(str, Enum):
    """Origin of tainted content."""
    WEB_SCRAPING = "web_scraping"
    SEARCH_RESULT = "search_result"
    USER_UPLOAD = "user_upload"
    EMAIL = "email"
    API_RESPONSE = "api_response"
    BROWSER = "browser"
    PLUGIN = "plugin"
    UNKNOWN = "unknown"


# Tools that modify external state — cannot be triggered by tainted content
DESTRUCTIVE_TOOLS: frozenset[str] = frozenset({
    "send_email",
    "delete_file",
    "delete_data",
    "make_payment",
    "publish_content",
    "push_code",
    "create_pr",
    "update_crm",
    "send_message",
    "drop_table",
    "execute_code",
    "modify_database",
})


@dataclass
class TaintLabel:
    """Metadata attached to tainted content."""
    source: TaintSource
    timestamp: str = ""
    trust_level: float = 0.0  # 0.0 = untrusted, 1.0 = fully trusted
    original_source: str = ""  # URL, filename, etc.
    chain: list[str] = field(default_factory=list)  # propagation chain

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class TaintViolation(Exception):
    """Raised when tainted content tries to trigger a destructive action."""

    def __init__(self, message: str, label: Optional["TaintLabel"] = None, tool: str = ""):
        self.label = label
        self.tool = tool
        super().__init__(message)


@dataclass
class TaintedContent:
    """Wraps content with its taint label."""
    content: str
    label: TaintLabel
    laundered: bool = False
    laundered_by: str = ""
    created_at: float = 0.0  # time.monotonic() for TTL

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()

    @property
    def is_tainted(self) -> bool:
        return not self.laundered and self.label.trust_level < 0.9


# Type for launder callback
LaunderCallback = Callable[[str, str, "TaintLabel"], None]


class TaintTracker:
    """Tracks and validates taint labels across the agent pipeline.

    Usage:
        # Basic
        tracker = TaintTracker()

        # Production (strict mode + salt)
        tracker = TaintTracker(strict_mode=True, salt="random-secret")

        # Label incoming external content
        tc = tracker.label("some web content", TaintSource.WEB_SCRAPING)

        # Validate before tool call
        tracker.validate_tool_call("some web content", "send_email")
        # Raises TaintViolation!

        # Human approves
        tracker.launder("some web content", approved_by="user@example.com")

        # Now it works
        tracker.validate_tool_call("some web content", "send_email")  # OK
    """

    def __init__(
        self,
        custom_destructive_tools: Optional[set[str]] = None,
        strict_mode: bool = False,
        salt: Optional[str] = None,
        max_entries: int = 50_000,
        ttl_seconds: int = 3600,
        on_launder: Optional[LaunderCallback] = None,
    ):
        self._registry: dict[str, TaintedContent] = {}
        self._destructive_tools = DESTRUCTIVE_TOOLS | (custom_destructive_tools or set())
        self._strict_mode = strict_mode
        self._salt = salt or os.urandom(16).hex()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._on_launder = on_launder
        self._lock = threading.Lock()
        self._ops_since_cleanup = 0
        self._cleanup_interval = 1000  # cleanup every N operations

    def label(
        self,
        content: str,
        source: TaintSource,
        trust_level: float = 0.0,
        original_source: str = "",
    ) -> TaintedContent:
        """Label content as tainted on ingestion."""
        label = TaintLabel(
            source=source,
            trust_level=min(max(trust_level, 0.0), 1.0),
            original_source=original_source[:500],  # Limit source length
            chain=[f"ingested:{source.value}"],
        )
        tc = TaintedContent(content=content, label=label)

        with self._lock:
            self._maybe_cleanup()
            content_hash = self._hash(content)

            # Enforce max entries
            if len(self._registry) >= self._max_entries and content_hash not in self._registry:
                self._evict_expired()
                if len(self._registry) >= self._max_entries:
                    # Evict oldest entry
                    oldest_key = min(self._registry, key=lambda k: self._registry[k].created_at)
                    del self._registry[oldest_key]
                    logger.warning("Taint registry full (%d), evicted oldest entry", self._max_entries)

            self._registry[content_hash] = tc

        logger.debug("Labeled: source=%s trust=%.2f", source.value, trust_level)
        return tc

    def propagate(self, original: TaintedContent, transformed_content: str) -> TaintedContent:
        """Propagate taint label when content is transformed."""
        new_label = TaintLabel(
            source=original.label.source,
            trust_level=original.label.trust_level,
            original_source=original.label.original_source,
            chain=original.label.chain + ["transformed"],
        )
        tc = TaintedContent(content=transformed_content, label=new_label)
        with self._lock:
            self._registry[self._hash(transformed_content)] = tc
        return tc

    def validate_tool_call(self, content: str, tool_name: str) -> bool:
        """Validate whether content can trigger a tool call.

        Returns True if allowed, raises TaintViolation if blocked.

        In strict_mode, unknown content (not in registry) is blocked from
        destructive tools. In normal mode, unknown content passes.
        """
        with self._lock:
            tc = self._registry.get(self._hash(content))

        if tc is None:
            if self._strict_mode and tool_name in self._destructive_tools:
                raise TaintViolation(
                    f"Unknown content cannot trigger destructive tool '{tool_name}' "
                    f"in strict mode — content must be explicitly registered",
                    tool=tool_name,
                )
            return True

        if not tc.is_tainted:
            return True

        if tool_name not in self._destructive_tools:
            return True

        raise TaintViolation(
            f"Tainted content (source={tc.label.source.value}, "
            f"trust={tc.label.trust_level:.2f}) cannot trigger "
            f"destructive tool '{tool_name}' without human approval",
            label=tc.label,
            tool=tool_name,
        )

    def launder(self, content: str, approved_by: str) -> bool:
        """Mark content as trusted after human approval.

        Records who approved and when. Calls on_launder callback if set.
        """
        if not approved_by:
            logger.warning("launder() called with empty approved_by — rejected")
            return False

        with self._lock:
            content_hash = self._hash(content)
            tc = self._registry.get(content_hash)

            if tc is None:
                return False

            tc.laundered = True
            tc.laundered_by = approved_by
            tc.label.chain.append(f"laundered_by:{approved_by}:{datetime.now(timezone.utc).isoformat()}")

        logger.info("Content laundered by %s (source=%s)", approved_by, tc.label.source.value)

        # Call callback outside lock to avoid deadlocks
        if self._on_launder:
            try:
                self._on_launder(content, approved_by, tc.label)
            except Exception as e:
                logger.error("on_launder callback failed: %s", e)

        return True

    def is_tainted(self, content: str) -> bool:
        """Check if content is tainted."""
        with self._lock:
            tc = self._registry.get(self._hash(content))
        return tc.is_tainted if tc else False

    def get_label(self, content: str) -> Optional[TaintLabel]:
        """Get the taint label for content."""
        with self._lock:
            tc = self._registry.get(self._hash(content))
        return tc.label if tc else None

    @property
    def registry_size(self) -> int:
        """Current number of entries in the registry."""
        return len(self._registry)

    def _hash(self, content: str) -> str:
        """Full SHA-256 hash with salt."""
        salted = f"{self._salt}:{content}"
        return hashlib.sha256(salted.encode()).hexdigest()

    def _maybe_cleanup(self) -> None:
        """Periodic cleanup of expired entries (called under lock)."""
        self._ops_since_cleanup += 1
        if self._ops_since_cleanup >= self._cleanup_interval:
            self._evict_expired()
            self._ops_since_cleanup = 0

    def _evict_expired(self) -> None:
        """Remove entries older than TTL (called under lock)."""
        now = time.monotonic()
        expired = [
            k for k, v in self._registry.items()
            if (now - v.created_at) > self._ttl_seconds
        ]
        for k in expired:
            del self._registry[k]
        if expired:
            logger.debug("Evicted %d expired taint entries", len(expired))
