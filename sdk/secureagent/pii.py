"""PII Detection — detects and redacts personally identifiable information.

Uses validated regex patterns for common PII types with per-pattern confidence
scoring. For production use, install the 'pii' extra for Presidio support.

Features:
- Validated IP addresses (octets 0-255)
- Luhn check for credit cards
- SSN range validation
- International phone patterns
- Per-pattern confidence scoring
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


def _luhn_check(number: str) -> bool:
    """Validate a number using the Luhn algorithm."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    reverse = digits[::-1]
    for i, d in enumerate(reverse):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _valid_ip(ip_str: str) -> bool:
    """Check if IP address has valid octets (0-255)."""
    parts = ip_str.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _valid_ssn(ssn_str: str) -> bool:
    """Validate SSN ranges (exclude known invalid prefixes)."""
    parts = ssn_str.split("-")
    if len(parts) != 3:
        return False
    area = int(parts[0])
    # Invalid: 000, 666, 900-999
    if area == 0 or area == 666 or area >= 900:
        return False
    group = int(parts[1])
    if group == 0:
        return False
    serial = int(parts[2])
    if serial == 0:
        return False
    return True


# PII patterns with associated confidence and optional validator
_PII_PATTERNS: list[tuple[str, re.Pattern, float, Optional[callable]]] = [
    (
        "email",
        re.compile(r'\b[A-Za-z0-9._%+\-]{2,}@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'),
        0.92,
        None,
    ),
    (
        "phone_us",
        re.compile(r'\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
        0.85,
        None,
    ),
    (
        "phone_international",
        re.compile(r'\b\+(?!1\b)\d{1,3}[-.\s]?\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b'),
        0.80,
        None,
    ),
    (
        "ssn",
        re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
        0.95,
        _valid_ssn,
    ),
    (
        "credit_card",
        re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
        0.90,
        lambda s: _luhn_check(s),
    ),
    (
        "ip_address",
        re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
        0.50,  # Low base confidence; IPs are often not PII
        _valid_ip,
    ),
    (
        "api_key",
        re.compile(
            r'\b(?:sk|pk|api|token|secret|key)[-_][A-Za-z0-9\-_]{20,}\b',
            re.IGNORECASE,
        ),
        0.88,
        None,
    ),
]

# Private IP ranges (lower PII risk)
_PRIVATE_IP_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                        "172.30.", "172.31.", "192.168.", "127.")


class PIIDetector:
    """Detects and optionally redacts PII from text.

    Usage:
        detector = PIIDetector()

        # Detect PII
        matches = detector.detect("Contact john@example.com or call 555-123-4567")

        # Redact PII
        clean = detector.redact("My SSN is 123-45-6789")
        # "My SSN is [SSN_REDACTED]"

        # Check if text contains PII
        has_pii = detector.contains_pii("Some text with john@test.com")
    """

    def __init__(
        self,
        enabled_types: Optional[list[str]] = None,
        use_presidio: bool = False,
        min_confidence: float = 0.5,
    ):
        if enabled_types:
            self._patterns = [p for p in _PII_PATTERNS if p[0] in enabled_types]
        else:
            self._patterns = list(_PII_PATTERNS)

        self._min_confidence = min_confidence
        self._presidio = None
        if use_presidio:
            try:
                from presidio_analyzer import AnalyzerEngine
                self._presidio = AnalyzerEngine()
                logger.info("Presidio PII analyzer loaded")
            except ImportError:
                logger.warning(
                    "Presidio not installed — using regex patterns. "
                    "Install with: pip install secureagent[pii]"
                )

    def detect(self, text: str) -> list[PIIMatch]:
        """Detect PII in text. Returns list of matches sorted by position."""
        if self._presidio:
            return self._detect_presidio(text)
        return self._detect_regex(text)

    def _detect_regex(self, text: str) -> list[PIIMatch]:
        matches = []
        for pii_type, pattern, base_confidence, validator in self._patterns:
            for match in pattern.finditer(text):
                value = match.group()
                confidence = base_confidence

                # Run validator if present
                if validator:
                    try:
                        if not validator(value):
                            continue  # Skip invalid matches
                    except Exception:
                        continue

                # Adjust confidence for IP addresses
                if pii_type == "ip_address":
                    if any(value.startswith(p) for p in _PRIVATE_IP_PREFIXES):
                        confidence = 0.35  # Private IPs rarely PII
                    elif value.startswith("0.") or value == "255.255.255.255":
                        continue  # Skip broadcast/zero addresses

                if confidence >= self._min_confidence:
                    matches.append(PIIMatch(
                        type=pii_type,
                        value=value,
                        start=match.start(),
                        end=match.end(),
                        confidence=confidence,
                    ))

        return sorted(matches, key=lambda m: m.start)

    def _detect_presidio(self, text: str) -> list[PIIMatch]:
        try:
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
                if r.score >= self._min_confidence
            ]
        except Exception as e:
            logger.error("Presidio analysis failed, falling back to regex: %s", e)
            return self._detect_regex(text)

    def contains_pii(self, text: str) -> bool:
        """Check if text contains any PII."""
        return len(self.detect(text)) > 0

    def redact(self, text: str, replacement: Optional[str] = None) -> str:
        """Redact all PII from text. Returns cleaned text."""
        matches = self.detect(text)
        if not matches:
            return text

        # Remove overlapping matches (keep highest confidence)
        filtered = self._remove_overlaps(matches)

        # Process from end to start to preserve positions
        result = text
        for match in reversed(filtered):
            tag = replacement or f"[{match.type.upper()}_REDACTED]"
            result = result[:match.start] + tag + result[match.end:]
        return result

    def scan_dict(self, data: dict, _depth: int = 0) -> dict[str, list[PIIMatch]]:
        """Scan all string values in a dict for PII. Max depth 5."""
        if _depth > 5:
            return {}
        results = {}
        for key, value in data.items():
            if isinstance(value, str):
                matches = self.detect(value)
                if matches:
                    results[key] = matches
            elif isinstance(value, dict):
                sub = self.scan_dict(value, _depth + 1)
                for sub_key, sub_matches in sub.items():
                    results[f"{key}.{sub_key}"] = sub_matches
        return results

    @staticmethod
    def _remove_overlaps(matches: list[PIIMatch]) -> list[PIIMatch]:
        """Remove overlapping matches, keeping the highest confidence one."""
        if not matches:
            return []
        sorted_matches = sorted(matches, key=lambda m: (-m.confidence, m.start))
        result = []
        occupied: list[tuple[int, int]] = []
        for match in sorted_matches:
            overlaps = any(
                match.start < end and match.end > start
                for start, end in occupied
            )
            if not overlaps:
                result.append(match)
                occupied.append((match.start, match.end))
        return sorted(result, key=lambda m: m.start)
