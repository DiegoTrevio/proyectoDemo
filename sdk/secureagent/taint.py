"""Taint Tracking — labels external content to prevent untrusted tool calls.

All content from external sources (web scraping, APIs, user documents, search
results) carries a TaintLabel. Tainted content cannot trigger destructive
tool calls without explicit human approval.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

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

    @property
    def is_tainted(self) -> bool:
        return not self.laundered and self.label.trust_level < 0.9


class TaintTracker:
    """Tracks and validates taint labels across the agent pipeline.

    Usage:
        tracker = TaintTracker()

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

    def __init__(self, custom_destructive_tools: Optional[set[str]] = None):
        self._registry: dict[str, TaintedContent] = {}
        self._destructive_tools = DESTRUCTIVE_TOOLS | (custom_destructive_tools or set())

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
            original_source=original_source,
            chain=[f"ingested:{source.value}"],
        )
        tc = TaintedContent(content=content, label=label)
        self._registry[self._hash(content)] = tc
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
        self._registry[self._hash(transformed_content)] = tc
        return tc

    def validate_tool_call(self, content: str, tool_name: str) -> bool:
        """Validate whether content can trigger a tool call.

        Returns True if allowed, raises TaintViolation if blocked.
        """
        tc = self._registry.get(self._hash(content))

        if tc is None or not tc.is_tainted:
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
        """Mark content as trusted after human approval."""
        tc = self._registry.get(self._hash(content))
        if tc is None:
            return False
        tc.laundered = True
        tc.laundered_by = approved_by
        tc.label.chain.append(f"laundered_by:{approved_by}")
        logger.info("Content laundered by %s", approved_by)
        return True

    def is_tainted(self, content: str) -> bool:
        """Check if content is tainted."""
        tc = self._registry.get(self._hash(content))
        return tc.is_tainted if tc else False

    def get_label(self, content: str) -> Optional[TaintLabel]:
        """Get the taint label for content."""
        tc = self._registry.get(self._hash(content))
        return tc.label if tc else None

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]
