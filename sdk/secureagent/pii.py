"""PII Detection — detects and redacts personally identifiable information.

Uses regex patterns for common PII types. For production use, install the
'pii' extra (`pip install secureagent[pii]`) which adds Presidio support.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("secureagent.pii")


@dataclass
class PIIMatch:
    """A detected PII instance."""
    type: str
    value: str
    start: int
    end: int
    confidence: float


# Regex patterns for common PII
_PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "phone_us": re.compile(r'\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
    "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    "credit_card": re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
    "ip_address": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    "api_key": re.compile(r'\b(?:sk|pk|api|key|token|secret)[-_][A-Za-z0-9]{16,}\b', re.IGNORECASE),
}


class PIIDetector:
    """Detects and optionally redacts PII from text.

    Usage:
        detector = PIIDetector()

        # Detect PII
        matches = detector.detect("Contact john@example.com or call 555-123-4567")
        # [PIIMatch(type="email", ...), PIIMatch(type="phone_us", ...)]

        # Redact PII
        clean = detector.redact("My SSN is 123-45-6789")
        # "My SSN is [SSN_REDACTED]"

        # Check if text contains PII
        has_pii = detector.contains_pii("Some text with john@test.com")
        # True
    """

    def __init__(
        self,
        enabled_types: Optional[list[str]] = None,
        use_presidio: bool = False,
    ):
        if enabled_types:
            self._patterns = {k: v for k, v in _PII_PATTERNS.items() if k in enabled_types}
        else:
            self._patterns = dict(_PII_PATTERNS)

        self._presidio = None
        if use_presidio:
            try:
                from presidio_analyzer import AnalyzerEngine
                self._presidio = AnalyzerEngine()
                logger.info("Presidio PII analyzer loaded")
            except ImportError:
                logger.warning("Presidio not installed — falling back to regex. pip install secureagent[pii]")

    def detect(self, text: str) -> list[PIIMatch]:
        """Detect PII in text. Returns list of matches."""
        if self._presidio:
            return self._detect_presidio(text)
        return self._detect_regex(text)

    def _detect_regex(self, text: str) -> list[PIIMatch]:
        matches = []
        for pii_type, pattern in self._patterns.items():
            for match in pattern.finditer(text):
                matches.append(PIIMatch(
                    type=pii_type,
                    value=match.group(),
                    start=match.start(),
                    end=match.end(),
                    confidence=0.85,
                ))
        return sorted(matches, key=lambda m: m.start)

    def _detect_presidio(self, text: str) -> list[PIIMatch]:
        results = self._presidio.analyze(text=text, language="en")
        return [
            PIIMatch(
                type=r.entity_type.lower(),
                value=text[r.start:r.end],
                start=r.start,
                end=r.end,
                confidence=r.score,
            )
            for r in results
        ]

    def contains_pii(self, text: str) -> bool:
        """Check if text contains any PII."""
        return len(self.detect(text)) > 0

    def redact(self, text: str, replacement: Optional[str] = None) -> str:
        """Redact all PII from text. Returns cleaned text."""
        matches = self.detect(text)
        if not matches:
            return text

        # Process from end to start to preserve positions
        result = text
        for match in reversed(matches):
            tag = replacement or f"[{match.type.upper()}_REDACTED]"
            result = result[:match.start] + tag + result[match.end:]
        return result

    def scan_dict(self, data: dict) -> dict[str, list[PIIMatch]]:
        """Scan all string values in a dict for PII."""
        results = {}
        for key, value in data.items():
            if isinstance(value, str):
                matches = self.detect(value)
                if matches:
                    results[key] = matches
            elif isinstance(value, dict):
                sub = self.scan_dict(value)
                for sub_key, sub_matches in sub.items():
                    results[f"{key}.{sub_key}"] = sub_matches
        return results
