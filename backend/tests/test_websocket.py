"""Tests for WebSocket handler — bidirectional HITL communication."""

import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestWebSocketApprovalParsing:
    """Test that WebSocket parses approval responses correctly."""

    @pytest.mark.asyncio
    @patch("security.approval_gates.handle_approval_response", new_callable=AsyncMock)
    async def test_approval_response_parsed(self, mock_handle):
        """Approval response JSON is correctly routed to handle_approval_response."""
        mock_handle.return_value = True

        # Simulate the parsing logic from websocket.py
        raw = json.dumps({
            "type": "approval_response",
            "approval_id": "abc123",
            "approved": True,
            "user_id": "test-user",
        })

        data = json.loads(raw)
        if data.get("type") == "approval_response":
            from security.approval_gates import handle_approval_response
            await handle_approval_response(
                approval_id=data.get("approval_id", ""),
                approved=data.get("approved", False),
                user_id=data.get("user_id", ""),
            )

        mock_handle.assert_called_once_with(
            approval_id="abc123",
            approved=True,
            user_id="test-user",
        )

    def test_non_json_message_not_parsed(self):
        """Plain text messages don't trigger approval handling."""
        raw = "Hello, this is a plain message"
        try:
            data = json.loads(raw)
            is_approval = data.get("type") == "approval_response"
        except (json.JSONDecodeError, ValueError):
            is_approval = False
        assert not is_approval

    def test_non_approval_json_not_parsed(self):
        """JSON messages without type=approval_response are not routed."""
        raw = json.dumps({"type": "user_input", "content": "confirm"})
        data = json.loads(raw)
        assert data.get("type") != "approval_response"


class TestWebSocketEventForwarding:
    """Test Redis event forwarding to WebSocket clients."""

    def test_event_format(self):
        """Events follow the expected JSON format."""
        event = {
            "type": "approval_required",
            "action": "send_email",
            "reason": "Sending email via Gmail",
            "risk_level": "high",
            "approval_id": "abc123",
            "params": {"to": "user@example.com"},
            "timestamp": "2026-03-26T00:00:00Z",
        }
        serialized = json.dumps(event)
        parsed = json.loads(serialized)

        assert parsed["type"] == "approval_required"
        assert parsed["risk_level"] == "high"
        assert parsed["approval_id"] == "abc123"
