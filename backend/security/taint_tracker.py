"""Taint Tracking — labels external content to prevent untrusted tool calls.

All content from external sources (web scraping, APIs, user documents, search
results) carries a TaintLabel. Tainted content cannot trigger destructive
tool calls without explicit human approval.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger("agentos.security.taint")


class TaintSource(str, Enum):
    """Origin of tainted content."""
    WEB_SCRAPING = "web_scraping"
    SEARCH_RESULT = "search_result"
    USER_UPLOAD = "user_upload"
    EMAIL = "email"
    API_RESPONSE = "api_response"
    COMPOSIO = "composio"
    BROWSER = "browser"
    UNKNOWN = "unknown"


# Tools that modify external state — cannot be triggered by tainted content
DESTRUCTIVE_TOOLS = frozenset({
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

    def __init__(self, message: str, label: "TaintLabel | None" = None, tool: str = ""):
        self.label = label
        self.tool = tool
        super().__init__(message)


@dataclass
class TaintedContent:
    """Wraps content with its taint label."""
    content: str
    label: TaintLabel
    laundered: bool = False  # True if human approved
    laundered_by: str = ""   # user_id who approved

    @property
    def is_tainted(self) -> bool:
        return not self.laundered and self.label.trust_level < 0.9


class TaintTracker:
    """Tracks and validates taint labels across the agent pipeline."""

    def __init__(self):
        self._registry: dict[str, TaintedContent] = {}  # content_hash -> TaintedContent

    def label(
        self,
        content: str,
        source: TaintSource,
        trust_level: float = 0.0,
        original_source: str = "",
    ) -> TaintedContent:
        """Label content as tainted on ingestion.

        Args:
            content: The raw content from external source.
            source: Where the content came from.
            trust_level: 0.0 (untrusted) to 1.0 (trusted).
            original_source: URL, filename, or identifier.

        Returns:
            TaintedContent wrapper.
        """
        label = TaintLabel(
            source=source,
            trust_level=min(max(trust_level, 0.0), 1.0),
            original_source=original_source,
            chain=[f"ingested:{source.value}"],
        )
        tc = TaintedContent(content=content, label=label)

        content_hash = self._hash(content)
        self._registry[content_hash] = tc

        logger.debug(
            "Labeled content as tainted: source=%s trust=%.2f src=%s",
            source.value, trust_level, original_source[:60],
        )
        return tc

    def propagate(self, original: TaintedContent, transformed_content: str) -> TaintedContent:
        """Propagate taint label when content is transformed.

        When tainted content is summarized, translated, or otherwise processed,
        the taint label follows the output.
        """
        new_label = TaintLabel(
            source=original.label.source,
            trust_level=original.label.trust_level,
            original_source=original.label.original_source,
            chain=original.label.chain + ["transformed"],
        )
        tc = TaintedContent(content=transformed_content, label=new_label)
        self._registry[self._hash(transformed_content)] = tc
        return tc

    def validate_tool_call(
        self,
        content: str,
        tool_name: str,
    ) -> bool:
        """Validate whether content can trigger a tool call.

        Returns True if allowed, raises TaintViolation if blocked.
        """
        content_hash = self._hash(content)
        tc = self._registry.get(content_hash)

        if tc is None:
            # Content not in registry — treat as clean
            return True

        if not tc.is_tainted:
            return True

        if tool_name not in DESTRUCTIVE_TOOLS:
            # Non-destructive tools are always allowed
            return True

        # Tainted content trying to trigger destructive tool
        raise TaintViolation(
            f"Tainted content (source={tc.label.source.value}, "
            f"trust={tc.label.trust_level:.2f}) cannot trigger "
            f"destructive tool '{tool_name}' without human approval",
            label=tc.label,
            tool=tool_name,
        )

    def launder(self, content: str, approved_by: str) -> bool:
        """Explicitly mark content as trusted after human approval.

        This is the ONLY way to allow tainted content to trigger destructive actions.
        """
        content_hash = self._hash(content)
        tc = self._registry.get(content_hash)

        if tc is None:
            return False

        tc.laundered = True
        tc.laundered_by = approved_by
        tc.label.chain.append(f"laundered_by:{approved_by}")

        logger.info(
            "Content laundered by %s (source=%s)",
            approved_by, tc.label.source.value,
        )
        return True

    def is_tainted(self, content: str) -> bool:
        """Check if content is tainted."""
        tc = self._registry.get(self._hash(content))
        return tc.is_tainted if tc else False

    def get_label(self, content: str) -> TaintLabel | None:
        """Get the taint label for content."""
        tc = self._registry.get(self._hash(content))
        return tc.label if tc else None

    @staticmethod
    def _hash(content: str) -> str:
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# Singleton
taint_tracker = TaintTracker()
