"""LLM Guard configuration — input/output scanners for security.

Configures Presidio-based PII detection, prompt injection detection,
toxicity filtering, and output validation scanners.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("agentos.security.llm_guard")


@dataclass
class ScanResult:
    """Result of a security scan."""
    sanitized_text: str
    is_safe: bool
    risks: dict[str, float] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)


# ─── Scanner registry ────────────────────────────────────────────────────

_input_scanners = None
_output_scanners = None


def _get_input_scanners():
    """Lazily initialize input scanners."""
    global _input_scanners
    if _input_scanners is not None:
        return _input_scanners

    try:
        from llm_guard.input_scanners import (
            BanTopics,
            PromptInjection,
            Regex,
            TokenLimit,
            Toxicity,
        )
        from llm_guard.input_scanners.prompt_injection import MatchType as PIMatchType

        _input_scanners = [
            PromptInjection(threshold=0.85, match_type=PIMatchType.FULL),
            Toxicity(threshold=0.8),
            Regex(
                patterns=[
                    r"\b\d{3}-\d{2}-\d{4}\b",          # SSN
                    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # Credit card
                ],
                is_blocked=True,
                redact=True,
            ),
            TokenLimit(limit=8192),
        ]
        logger.info("LLM Guard input scanners initialized: %d scanners",
                     len(_input_scanners))
    except ImportError:
        logger.warning("llm-guard not installed — using fallback scanners")
        _input_scanners = []

    return _input_scanners


def _get_output_scanners():
    """Lazily initialize output scanners."""
    global _output_scanners
    if _output_scanners is not None:
        return _output_scanners

    try:
        from llm_guard.output_scanners import (
            BanTopics,
            NoRefusal,
            Regex,
            Relevance,
            Sensitive,
        )

        _output_scanners = [
            Sensitive(redact=True),
            Regex(
                patterns=[
                    r"\b\d{3}-\d{2}-\d{4}\b",          # SSN
                    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # Credit card
                ],
                is_blocked=True,
                redact=True,
            ),
            NoRefusal(threshold=0.5),
        ]
        logger.info("LLM Guard output scanners initialized: %d scanners",
                     len(_output_scanners))
    except ImportError:
        logger.warning("llm-guard not installed — using fallback output scanners")
        _output_scanners = []

    return _output_scanners


# ─── Scan functions ──────────────────────────────────────────────────────

def scan_input(text: str) -> ScanResult:
    """Scan user input for security risks.

    Checks for: prompt injection, toxicity, PII (via regex), token limits.

    Returns:
        ScanResult with sanitized text, safety flag, and risk scores.
    """
    scanners = _get_input_scanners()

    if not scanners:
        # Fallback: basic regex-based PII detection
        return _fallback_scan_input(text)

    try:
        from llm_guard import scan_prompt

        sanitized, results_valid, results_score = scan_prompt(scanners, text)

        risks = {}
        details = []
        is_safe = True

        for scanner, valid, score in zip(scanners, results_valid, results_score):
            scanner_name = type(scanner).__name__
            risks[scanner_name] = score
            if not valid:
                is_safe = False
                details.append(f"{scanner_name} flagged (score: {score:.2f})")

        return ScanResult(
            sanitized_text=sanitized,
            is_safe=is_safe,
            risks=risks,
            details=details,
        )
    except Exception as e:
        logger.exception("Input scan error — falling back")
        return _fallback_scan_input(text)


def scan_output(text: str, prompt: str = "") -> ScanResult:
    """Scan LLM output for security risks.

    Checks for: PII leakage, sensitive data, bias indicators.

    Returns:
        ScanResult with sanitized text, safety flag, and risk scores.
    """
    scanners = _get_output_scanners()

    if not scanners:
        return _fallback_scan_output(text)

    try:
        from llm_guard import scan_output as llm_guard_scan

        sanitized, results_valid, results_score = llm_guard_scan(
            scanners, prompt, text
        )

        risks = {}
        details = []
        is_safe = True

        for scanner, valid, score in zip(scanners, results_valid, results_score):
            scanner_name = type(scanner).__name__
            risks[scanner_name] = score
            if not valid:
                is_safe = False
                details.append(f"{scanner_name} flagged (score: {score:.2f})")

        return ScanResult(
            sanitized_text=sanitized,
            is_safe=is_safe,
            risks=risks,
            details=details,
        )
    except Exception as e:
        logger.exception("Output scan error — falling back")
        return _fallback_scan_output(text)


# ─── Fallback regex-based scanners ───────────────────────────────────────

import re

_PII_PATTERNS = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CreditCard": re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    "Email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "Phone": re.compile(r"\b(?:\+1[\s-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"),
    "IPAddress": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+your\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"forget\s+(your|previous)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions\s*:", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"reveal\s+your\s+(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"output\s+your\s+initial\s+prompt", re.IGNORECASE),
    re.compile(r"\bDAN\s+mode\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
]


def _fallback_scan_input(text: str) -> ScanResult:
    """Regex-based fallback for input scanning."""
    risks = {}
    details = []
    sanitized = text

    # Check prompt injection
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            risks["PromptInjection"] = 1.0
            details.append(f"Prompt injection detected: {pattern.pattern}")
            return ScanResult(
                sanitized_text="",
                is_safe=False,
                risks=risks,
                details=details,
            )

    # Check PII
    sanitized, pii_risks, pii_details = _redact_pii(text)
    risks.update(pii_risks)
    details.extend(pii_details)

    return ScanResult(
        sanitized_text=sanitized,
        is_safe=not bool(pii_risks),
        risks=risks,
        details=details,
    )


def _fallback_scan_output(text: str) -> ScanResult:
    """Regex-based fallback for output scanning."""
    sanitized, pii_risks, pii_details = _redact_pii(text)
    return ScanResult(
        sanitized_text=sanitized,
        is_safe=not bool(pii_risks),
        risks=pii_risks,
        details=pii_details,
    )


def _redact_pii(text: str) -> tuple[str, dict, list]:
    """Redact PII from text, return (sanitized, risks, details)."""
    risks = {}
    details = []
    sanitized = text

    for pii_type, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(sanitized)
        if matches:
            risks[pii_type] = 1.0
            details.append(f"Detected {len(matches)} {pii_type} instance(s)")
            sanitized = pattern.sub(f"[REDACTED_{pii_type}]", sanitized)

    return sanitized, risks, details
