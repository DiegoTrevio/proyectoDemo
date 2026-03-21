"""Edge case tests for SecureAgent SDK."""

import asyncio
import pytest

from secureagent import (
    AuditLog,
    PIIDetector,
    SecureAgent,
    TaintSource,
    TaintTracker,
)
from secureagent.core import SecurityViolation, _validate_tool_name
from secureagent.gates import ApprovalGate


# ─── Input Validation ───────────────────────────────────────────────────

class TestInputValidation:
    def test_empty_tool_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_tool_name("")

    def test_invalid_tool_name_raises(self):
        with pytest.raises(ValueError, match="Invalid tool_name"):
            _validate_tool_name("tool with spaces")

    def test_tool_name_too_long(self):
        with pytest.raises(ValueError, match="Invalid tool_name"):
            _validate_tool_name("a" * 101)

    def test_valid_tool_names(self):
        assert _validate_tool_name("search_web") == "search_web"
        assert _validate_tool_name("tool.name") == "tool.name"
        assert _validate_tool_name("tool-name") == "tool-name"
        assert _validate_tool_name("Tool123") == "Tool123"

    @pytest.mark.asyncio
    async def test_secure_call_validates_tool_name(self):
        agent = SecureAgent()

        async def mock(): return "ok"

        with pytest.raises(ValueError):
            await agent.secure_call(tool_name="", tool_fn=mock)


# ─── Unicode & Special Characters ────────────────────────────────────────

class TestUnicode:
    def test_taint_unicode_content(self):
        tracker = TaintTracker()
        tc = tracker.label("日本語テキスト", TaintSource.WEB_SCRAPING)
        assert tc.is_tainted
        assert tracker.is_tainted("日本語テキスト")

    def test_taint_emoji_content(self):
        tracker = TaintTracker()
        tc = tracker.label("Hello 🌍🔒", TaintSource.EMAIL)
        assert tc.is_tainted

    def test_audit_unicode(self):
        log = AuditLog()
        log.add_event("sess", "agent", "action", input_data="données françaises")
        trail = log.export_chain("sess")
        assert len(trail) == 1

    def test_pii_unicode_email(self):
        detector = PIIDetector()
        matches = detector.detect("Email: user@example.co.jp")
        assert len(matches) == 1
        assert matches[0].type == "email"


# ─── Large Payloads ─────────────────────────────────────────────────────

class TestLargePayloads:
    def test_large_content_in_taint(self):
        tracker = TaintTracker()
        large_content = "x" * 100_000  # 100KB
        tc = tracker.label(large_content, TaintSource.API_RESPONSE)
        assert tc.is_tainted

    def test_audit_metadata_truncation(self):
        log = AuditLog()
        large_metadata = {"key": "x" * 10_000}
        log.add_event("sess", "agent", "action", metadata=large_metadata)
        trail = log.export_chain("sess")
        # Metadata should be truncated
        assert trail[0]["metadata"].get("_truncated", False)


# ─── Empty / None Values ────────────────────────────────────────────────

class TestEmptyValues:
    def test_empty_string_taint(self):
        tracker = TaintTracker()
        tc = tracker.label("", TaintSource.UNKNOWN)
        assert tc.is_tainted

    def test_audit_empty_strings(self):
        log = AuditLog()
        log.add_event("", "", "")
        trail = log.export_chain("")
        assert len(trail) == 1

    def test_pii_empty_string(self):
        detector = PIIDetector()
        assert not detector.contains_pii("")
        assert detector.redact("") == ""


# ─── Taint Strict Mode ──────────────────────────────────────────────────

class TestStrictMode:
    def test_unknown_content_blocked_in_strict_mode(self):
        tracker = TaintTracker(strict_mode=True)
        from secureagent.taint import TaintViolation
        with pytest.raises(TaintViolation, match="strict mode"):
            tracker.validate_tool_call("unknown content", "send_email")

    def test_unknown_content_allowed_for_safe_tools_in_strict(self):
        tracker = TaintTracker(strict_mode=True)
        assert tracker.validate_tool_call("unknown", "search_web") is True

    def test_launder_requires_approved_by(self):
        tracker = TaintTracker()
        tracker.label("content", TaintSource.EMAIL)
        result = tracker.launder("content", approved_by="")
        assert result is False  # Should reject empty approver


# ─── Audit Signing ──────────────────────────────────────────────────────

class TestAuditSigning:
    def test_signed_chain_valid(self):
        log = AuditLog(signing_key="test-secret-key")
        log.add_event("sess", "agent", "action1")
        log.add_event("sess", "agent", "action2")

        valid, msg = log.verify_chain("sess")
        assert valid
        assert "2 events" in msg

    def test_signed_events_have_signatures(self):
        log = AuditLog(signing_key="test-secret-key")
        log.add_event("sess", "agent", "action1")
        trail = log.export_chain("sess")
        assert "signature" in trail[0]
        assert len(trail[0]["signature"]) == 64  # HMAC-SHA256

    def test_tamper_detected_with_signing(self):
        log = AuditLog(signing_key="test-secret-key")
        log.add_event("sess", "agent", "action1")

        # Tamper with the event
        log._chains["sess"][0].agent_id = "tampered"

        valid, msg = log.verify_chain("sess")
        assert not valid

    def test_unsigned_chain_still_works(self):
        log = AuditLog()  # No signing key
        log.add_event("sess", "agent", "action1")
        valid, msg = log.verify_chain("sess")
        assert valid


# ─── Bounded Structures ─────────────────────────────────────────────────

class TestBoundedStructures:
    def test_audit_chain_eviction(self):
        log = AuditLog(max_events_per_session=10)
        for i in range(20):
            log.add_event("sess", "agent", f"action_{i}")
        trail = log.export_chain("sess")
        assert len(trail) == 10

    def test_audit_max_sessions(self):
        log = AuditLog(max_sessions=5)
        for i in range(10):
            log.add_event(f"sess_{i}", "agent", "action")
        # Should have at most 5 sessions
        stats_count = sum(1 for s in [f"sess_{i}" for i in range(10)] if log.export_chain(s))
        assert stats_count <= 6  # 5 max + possibly 1 being added

    def test_taint_registry_eviction(self):
        tracker = TaintTracker(max_entries=10, ttl_seconds=3600)
        for i in range(20):
            tracker.label(f"content_{i}", TaintSource.WEB_SCRAPING)
        assert tracker.registry_size <= 10

    def test_gates_history_bounded(self):
        gate = ApprovalGate(risk_map={"search": "low"}, max_history=5)
        loop = asyncio.new_event_loop()
        for i in range(10):
            loop.run_until_complete(gate.check("search", session_id=f"s_{i}"))
        loop.close()
        assert gate.history_size == 5


# ─── Approval Gate Edge Cases ───────────────────────────────────────────

class TestGateEdgeCases:
    @pytest.mark.asyncio
    async def test_callback_returns_non_bool(self):
        async def bad_callback(request):
            return "yes"  # Not a bool

        gate = ApprovalGate(
            risk_map={"tool": "high"},
            approval_callback=bad_callback,
        )
        result = await gate.check("tool")
        assert result is False  # Should treat as rejected

    @pytest.mark.asyncio
    async def test_callback_raises_exception(self):
        async def error_callback(request):
            raise RuntimeError("callback crashed")

        gate = ApprovalGate(
            risk_map={"tool": "high"},
            approval_callback=error_callback,
        )
        result = await gate.check("tool")
        assert result is False  # Should treat as rejected

    @pytest.mark.asyncio
    async def test_callback_timeout(self):
        async def slow_callback(request):
            await asyncio.sleep(10)
            return True

        gate = ApprovalGate(
            risk_map={"tool": "high"},
            approval_callback=slow_callback,
            timeout=1,  # 1 second timeout
        )
        result = await gate.check("tool")
        assert result is False  # Should timeout

    @pytest.mark.asyncio
    async def test_invalid_risk_level_defaults_medium(self):
        gate = ApprovalGate(risk_map={"tool": "invalid_level"})
        assert gate.get_risk("tool").value == "medium"


# ─── PII Edge Cases ─────────────────────────────────────────────────────

class TestPIIEdgeCases:
    def test_overlapping_pii_matches(self):
        detector = PIIDetector()
        text = "Contact john@gmail.com and mary@gmail.com"
        matches = detector.detect(text)
        # Should find both emails
        emails = [m for m in matches if m.type == "email"]
        assert len(emails) == 2

    def test_invalid_ip_filtered(self):
        detector = PIIDetector()
        matches = detector.detect("IP: 999.999.999.999")
        ip_matches = [m for m in matches if m.type == "ip_address"]
        assert len(ip_matches) == 0  # Invalid IP should be filtered

    def test_valid_ip_detected(self):
        detector = PIIDetector()
        matches = detector.detect("Server: 203.0.113.50")
        ip_matches = [m for m in matches if m.type == "ip_address"]
        assert len(ip_matches) == 1

    def test_private_ip_low_confidence(self):
        detector = PIIDetector()
        matches = detector.detect("Network: 192.168.1.1")
        ip_matches = [m for m in matches if m.type == "ip_address"]
        if ip_matches:
            assert ip_matches[0].confidence < 0.5

    def test_invalid_ssn_filtered(self):
        detector = PIIDetector()
        # 000-xx-xxxx is invalid
        matches = detector.detect("ID: 000-12-3456")
        ssn_matches = [m for m in matches if m.type == "ssn"]
        assert len(ssn_matches) == 0

    def test_valid_ssn_detected(self):
        detector = PIIDetector()
        matches = detector.detect("SSN: 123-45-6789")
        ssn_matches = [m for m in matches if m.type == "ssn"]
        assert len(ssn_matches) == 1
        assert ssn_matches[0].confidence >= 0.9

    def test_credit_card_luhn_check(self):
        detector = PIIDetector()
        # Valid Visa test number
        matches = detector.detect("Card: 4111 1111 1111 1111")
        cc_matches = [m for m in matches if m.type == "credit_card"]
        assert len(cc_matches) == 1

    def test_invalid_credit_card_filtered(self):
        detector = PIIDetector()
        # Invalid Luhn
        matches = detector.detect("Card: 1234 5678 9012 3456")
        cc_matches = [m for m in matches if m.type == "credit_card"]
        assert len(cc_matches) == 0

    def test_redact_preserves_non_pii(self):
        detector = PIIDetector()
        text = "Hello world, contact john@example.com for info"
        result = detector.redact(text)
        assert "Hello world" in result
        assert "for info" in result
        assert "john@example.com" not in result

    def test_min_confidence_filter(self):
        detector = PIIDetector(min_confidence=0.90)
        # Private IPs have confidence 0.35, should be filtered
        matches = detector.detect("192.168.1.1")
        ip_matches = [m for m in matches if m.type == "ip_address"]
        assert len(ip_matches) == 0


# ─── Error Recovery ──────────────────────────────────────────────────────

class TestErrorRecovery:
    @pytest.mark.asyncio
    async def test_tool_error_still_audited(self):
        agent = SecureAgent(audit_log=True, pii_detection=False, taint_tracking=False)

        async def failing_tool():
            raise RuntimeError("tool crashed")

        with pytest.raises(RuntimeError, match="tool crashed"):
            await agent.secure_call(
                tool_name="failing_tool",
                tool_fn=failing_tool,
                session_id="error_test",
            )

        # Error should be in audit trail
        trail = agent.export_audit("error_test")
        assert len(trail) == 1
        assert trail[0]["action"] == "tool_error"
