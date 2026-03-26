"""Tests for approval gates — human-in-the-loop safety mechanism."""

import asyncio

import pytest

from security.approval_gates import (
    HIGH_RISK_ACTIONS,
    RiskLevel,
    handle_approval_response,
    is_high_risk,
    request_approval,
)


class TestIsHighRisk:
    """Test HIGH_RISK_ACTIONS registry."""

    def test_known_high_risk_actions(self):
        """All registered actions are detected as high risk."""
        for action in HIGH_RISK_ACTIONS:
            assert is_high_risk(action), f"{action} should be high risk"

    def test_code_execute_is_high_risk(self):
        """code_execute was added as a high-risk action."""
        assert is_high_risk("code_execute")

    def test_unknown_action_not_high_risk(self):
        """Actions not in registry are not high risk."""
        assert not is_high_risk("read_file")
        assert not is_high_risk("search_web")
        assert not is_high_risk("browser_navigate")


class TestRequestApproval:
    """Test approval request flow for different risk levels."""

    @pytest.mark.asyncio
    async def test_low_risk_returns_true_immediately(self):
        """LOW risk actions are logged and approved immediately."""
        result = await request_approval(
            task_id="test-123",
            action="read_file",
            reason="Reading a local file",
            risk_level=RiskLevel.LOW,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_medium_risk_returns_true(self):
        """MEDIUM risk actions notify but approve immediately."""
        with pytest.MonkeyPatch.context() as mp:
            # Mock Redis to avoid connection
            mp.setattr("security.approval_gates.aioredis", _mock_redis_module())
            result = await request_approval(
                task_id="test-123",
                action="browser_navigate",
                reason="Navigating to external URL",
                risk_level=RiskLevel.MEDIUM,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_high_risk_blocks_until_approval(self):
        """HIGH risk actions block until handle_approval_response is called."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("security.approval_gates.aioredis", _mock_redis_module())

            async def _approve_later():
                await asyncio.sleep(0.1)
                # Find the pending approval and approve it
                from security.approval_gates import _pending
                for aid in list(_pending.keys()):
                    await handle_approval_response(aid, True, "test-user")

            # Run approval and the auto-approver concurrently
            approve_task = asyncio.create_task(_approve_later())
            result = await request_approval(
                task_id="test-456",
                action="send_email",
                reason="Sending email",
                risk_level=RiskLevel.HIGH,
            )
            await approve_task
            assert result is True

    @pytest.mark.asyncio
    async def test_high_risk_timeout_returns_false(self):
        """HIGH risk actions return False on timeout."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("security.approval_gates.aioredis", _mock_redis_module())
            # Temporarily reduce timeout
            mp.setattr("security.approval_gates.APPROVAL_TIMEOUT", 0.1)

            result = await request_approval(
                task_id="test-timeout",
                action="delete_file",
                reason="Deleting important file",
                risk_level=RiskLevel.HIGH,
            )
            assert result is False


class TestHandleApprovalResponse:
    """Test resolving pending approvals."""

    @pytest.mark.asyncio
    async def test_resolve_pending_approval(self):
        """handle_approval_response resolves a pending future."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("security.approval_gates.aioredis", _mock_redis_module())
            from security.approval_gates import _pending

            # Create a pending future manually
            loop = asyncio.get_event_loop()
            future = loop.create_future()
            _pending["test-approval"] = future

            result = await handle_approval_response("test-approval", True, "admin")
            assert result is True
            assert future.result() is True
            assert "test-approval" not in _pending

    @pytest.mark.asyncio
    async def test_unknown_approval_id(self):
        """Returns False for unknown approval IDs."""
        result = await handle_approval_response("nonexistent", True)
        assert result is False


def _mock_redis_module():
    """Create a mock Redis module that provides async operations."""
    from unittest.mock import AsyncMock, MagicMock

    mock_module = MagicMock()
    mock_r = AsyncMock()
    mock_r.publish = AsyncMock()
    mock_r.set = AsyncMock()
    mock_r.close = AsyncMock()
    mock_module.from_url.return_value = mock_r
    return mock_module
