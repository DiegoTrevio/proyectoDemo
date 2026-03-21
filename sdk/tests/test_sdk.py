"""Tests for the SecureAgent SDK."""

import asyncio
import pytest

from secureagent import SecureAgent, TaintTracker, TaintSource, AuditLog, PIIDetector, RiskLevel
from secureagent.core import SecurityViolation
from secureagent.gates import ApprovalGate
from secureagent.middleware import secure_tool, SecureToolRegistry


# ─── Taint Tracking Tests ───────────────────────────────────────────────

class TestTaintTracker:
    def test_label_content(self):
        tracker = TaintTracker()
        tc = tracker.label("web content", TaintSource.WEB_SCRAPING)
        assert tc.is_tainted
        assert tc.label.source == TaintSource.WEB_SCRAPING
        assert tc.label.trust_level == 0.0

    def test_tainted_content_blocks_destructive_tools(self):
        tracker = TaintTracker()
        tracker.label("malicious input", TaintSource.WEB_SCRAPING)
        with pytest.raises(Exception, match="cannot trigger destructive tool"):
            tracker.validate_tool_call("malicious input", "send_email")

    def test_non_destructive_tools_allowed(self):
        tracker = TaintTracker()
        tracker.label("web content", TaintSource.WEB_SCRAPING)
        assert tracker.validate_tool_call("web content", "search_web") is True

    def test_launder_allows_destructive(self):
        tracker = TaintTracker()
        tracker.label("content", TaintSource.EMAIL)
        tracker.launder("content", approved_by="admin@test.com")
        assert tracker.validate_tool_call("content", "send_email") is True

    def test_unknown_content_passes(self):
        tracker = TaintTracker()
        assert tracker.validate_tool_call("never seen before", "send_email") is True

    def test_high_trust_passes(self):
        tracker = TaintTracker()
        tracker.label("trusted", TaintSource.API_RESPONSE, trust_level=0.95)
        assert tracker.validate_tool_call("trusted", "send_email") is True

    def test_propagate_keeps_taint(self):
        tracker = TaintTracker()
        original = tracker.label("raw data", TaintSource.WEB_SCRAPING)
        transformed = tracker.propagate(original, "summarized data")
        assert transformed.is_tainted

    def test_custom_destructive_tools(self):
        tracker = TaintTracker(custom_destructive_tools={"my_dangerous_tool"})
        tracker.label("content", TaintSource.WEB_SCRAPING)
        with pytest.raises(Exception):
            tracker.validate_tool_call("content", "my_dangerous_tool")


# ─── Audit Log Tests ────────────────────────────────────────────────────

class TestAuditLog:
    def test_add_event(self):
        log = AuditLog()
        hash1 = log.add_event(
            session_id="test_session",
            agent_id="test_agent",
            action="tool_call",
            tool_name="search",
            input_data="query",
            output_data="results",
        )
        assert hash1
        assert len(hash1) == 64  # SHA-256

    def test_chain_integrity(self):
        log = AuditLog()
        log.add_event("sess", "agent1", "call1", input_data="in1")
        log.add_event("sess", "agent1", "call2", input_data="in2")
        log.add_event("sess", "agent2", "call3", input_data="in3")

        valid, msg = log.verify_chain("sess")
        assert valid
        assert "3 events" in msg

    def test_export_chain(self):
        log = AuditLog()
        log.add_event("sess", "agent1", "call1")
        log.add_event("sess", "agent1", "call2")

        trail = log.export_chain("sess")
        assert len(trail) == 2
        assert trail[0]["agent_id"] == "agent1"
        assert trail[0]["prev_hash"] == "genesis"

    def test_get_stats(self):
        log = AuditLog()
        log.add_event("sess", "agent1", "call1", tokens_used=100, cost=0.01)
        log.add_event("sess", "agent2", "call2", tokens_used=200, cost=0.02)

        stats = log.get_stats("sess")
        assert stats["events"] == 2
        assert stats["total_tokens"] == 300
        assert stats["total_cost"] == pytest.approx(0.03)
        assert set(stats["agents"]) == {"agent1", "agent2"}

    def test_empty_chain_valid(self):
        log = AuditLog()
        valid, msg = log.verify_chain("nonexistent")
        assert valid

    def test_tamper_detection(self):
        log = AuditLog()
        log.add_event("sess", "agent1", "call1")
        # Tamper with the event
        log._chains["sess"][0].agent_id = "tampered"
        valid, msg = log.verify_chain("sess")
        assert not valid
        assert "mismatch" in msg.lower()


# ─── PII Detector Tests ─────────────────────────────────────────────────

class TestPIIDetector:
    def test_detect_email(self):
        detector = PIIDetector()
        matches = detector.detect("Contact john@example.com for info")
        assert len(matches) == 1
        assert matches[0].type == "email"
        assert matches[0].value == "john@example.com"

    def test_detect_phone(self):
        detector = PIIDetector()
        matches = detector.detect("Call me at 555-123-4567")
        assert len(matches) >= 1
        assert any(m.type == "phone_us" for m in matches)

    def test_detect_ssn(self):
        detector = PIIDetector()
        matches = detector.detect("SSN: 123-45-6789")
        assert any(m.type == "ssn" for m in matches)

    def test_detect_credit_card(self):
        detector = PIIDetector()
        matches = detector.detect("Card: 4111-1111-1111-1111")
        assert any(m.type == "credit_card" for m in matches)

    def test_redact(self):
        detector = PIIDetector()
        result = detector.redact("Email: john@example.com")
        assert "john@example.com" not in result
        assert "[EMAIL_REDACTED]" in result

    def test_contains_pii(self):
        detector = PIIDetector()
        assert detector.contains_pii("john@test.com")
        assert not detector.contains_pii("no pii here")

    def test_scan_dict(self):
        detector = PIIDetector()
        results = detector.scan_dict({
            "name": "John",
            "email": "john@test.com",
            "notes": "No PII",
        })
        assert "email" in results

    def test_api_key_detection(self):
        detector = PIIDetector()
        matches = detector.detect("Use key sk-1234567890abcdef1234567890")
        assert any(m.type == "api_key" for m in matches)


# ─── Approval Gate Tests ────────────────────────────────────────────────

class TestApprovalGate:
    @pytest.mark.asyncio
    async def test_low_risk_auto_approved(self):
        gate = ApprovalGate(risk_map={"search": "low"})
        result = await gate.check("search", session_id="test")
        assert result is True

    @pytest.mark.asyncio
    async def test_medium_risk_auto_approved(self):
        gate = ApprovalGate(risk_map={"send_message": "medium"})
        result = await gate.check("send_message", session_id="test")
        assert result is True

    @pytest.mark.asyncio
    async def test_high_risk_rejected_without_callback(self):
        gate = ApprovalGate(risk_map={"send_email": "high"})
        result = await gate.check("send_email", session_id="test")
        assert result is False

    @pytest.mark.asyncio
    async def test_high_risk_approved_with_callback(self):
        async def approve_all(request):
            return True

        gate = ApprovalGate(
            risk_map={"send_email": "high"},
            approval_callback=approve_all,
        )
        result = await gate.check("send_email", session_id="test")
        assert result is True

    @pytest.mark.asyncio
    async def test_high_risk_rejected_with_callback(self):
        async def reject_all(request):
            return False

        gate = ApprovalGate(
            risk_map={"send_email": "high"},
            approval_callback=reject_all,
        )
        result = await gate.check("send_email", session_id="test")
        assert result is False

    @pytest.mark.asyncio
    async def test_history_tracking(self):
        gate = ApprovalGate(risk_map={"search": "low"})
        await gate.check("search", session_id="test")
        history = gate.get_history()
        assert len(history) == 1
        assert history[0]["status"] == "approved"


# ─── SecureAgent Integration Tests ──────────────────────────────────────

class TestSecureAgent:
    @pytest.mark.asyncio
    async def test_basic_secure_call(self):
        agent = SecureAgent(
            taint_tracking=True,
            pii_detection=True,
            audit_log=True,
        )

        async def mock_tool(query: str = ""):
            return {"results": ["item1", "item2"]}

        result = await agent.secure_call(
            tool_name="search_web",
            tool_fn=mock_tool,
            args={"query": "python security"},
            session_id="test_sess",
        )
        assert result == {"results": ["item1", "item2"]}

    @pytest.mark.asyncio
    async def test_taint_blocks_destructive(self):
        agent = SecureAgent(taint_tracking=True)
        agent.label_content("malicious", TaintSource.WEB_SCRAPING)

        async def mock_send(to: str = "", body: str = ""):
            return "sent"

        with pytest.raises(SecurityViolation, match="Tainted content"):
            await agent.secure_call(
                tool_name="send_email",
                tool_fn=mock_send,
                args={"to": "test@test.com", "body": "hello"},
                input_context="malicious",
            )

    @pytest.mark.asyncio
    async def test_approval_gate_blocks(self):
        agent = SecureAgent(
            approval_gates={"send_email": "high"},
        )

        async def mock_send(to: str = "", body: str = ""):
            return "sent"

        with pytest.raises(SecurityViolation, match="approval"):
            await agent.secure_call(
                tool_name="send_email",
                tool_fn=mock_send,
                args={"to": "test@test.com", "body": "hello"},
            )

    @pytest.mark.asyncio
    async def test_audit_trail_recorded(self):
        agent = SecureAgent(audit_log=True)

        async def mock_tool():
            return "done"

        await agent.secure_call(
            tool_name="search",
            tool_fn=mock_tool,
            session_id="audit_test",
        )

        trail = agent.export_audit("audit_test")
        assert len(trail) == 1
        assert trail[0]["action"] == "tool_call"

    @pytest.mark.asyncio
    async def test_pii_detection_in_args(self):
        agent = SecureAgent(pii_detection=True, audit_log=True)

        async def mock_tool(data: str = ""):
            return "processed"

        result = await agent.secure_call(
            tool_name="process",
            tool_fn=mock_tool,
            args={"data": "Contact john@example.com"},
            session_id="pii_test",
        )
        assert result == "processed"

    def test_redact_pii(self):
        agent = SecureAgent(pii_detection=True)
        result = agent.redact_pii("My email is john@example.com")
        assert "john@example.com" not in result

    def test_verify_audit_chain(self):
        agent = SecureAgent(audit_log=True)
        valid, msg = agent.verify_audit("nonexistent")
        assert valid


# ─── Middleware Tests ────────────────────────────────────────────────────

class TestMiddleware:
    @pytest.mark.asyncio
    async def test_secure_tool_decorator(self):
        agent = SecureAgent(audit_log=True)

        @secure_tool(agent, session_id="dec_test")
        async def my_search(query: str = ""):
            return f"results for {query}"

        result = await my_search(query="test")
        assert "results for test" in result

    @pytest.mark.asyncio
    async def test_secure_tool_registry(self):
        agent = SecureAgent(audit_log=True)
        registry = SecureToolRegistry(agent, session_id="reg_test")

        async def search(query: str = ""):
            return f"found: {query}"

        registry.register("search", search)
        result = await registry.call("search", query="hello")
        assert "found: hello" in result

    @pytest.mark.asyncio
    async def test_registry_unknown_tool(self):
        agent = SecureAgent()
        registry = SecureToolRegistry(agent)
        with pytest.raises(ValueError, match="not registered"):
            await registry.call("nonexistent")
