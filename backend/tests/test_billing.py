"""Tests for billing middleware and usage tracking."""

import json

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from integrations.billing_middleware import BillingMiddleware


class TestBillingMiddleware:
    """Test plan limit enforcement."""

    @pytest.mark.asyncio
    async def test_skips_non_task_creation(self):
        """Middleware only checks POST /api/v1/tasks."""
        middleware = BillingMiddleware(app=MagicMock())
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/api/v1/tasks"
        call_next = AsyncMock(return_value=MagicMock())

        result = await middleware.dispatch(request, call_next)
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_without_user_id(self):
        """Passes through if no user_id in request state."""
        middleware = BillingMiddleware(app=MagicMock())
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/tasks"
        request.state = MagicMock(spec=[])  # No user_id attribute
        call_next = AsyncMock(return_value=MagicMock())

        result = await middleware.dispatch(request, call_next)
        call_next.assert_called_once()

    @pytest.mark.asyncio
    @patch("integrations.billing_middleware.get_usage")
    @patch("integrations.billing_middleware.get_plan")
    async def test_allows_under_limit(self, mock_plan, mock_usage):
        """Allows requests when under task limit."""
        mock_usage.return_value = {"plan": "starter", "tasks_used": 5}
        plan_obj = MagicMock()
        plan_obj.task_limit = 100
        plan_obj.models = ["agentOS/workhorse"]
        mock_plan.return_value = plan_obj

        middleware = BillingMiddleware(app=MagicMock())
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/tasks"
        request.state.user_id = "test-user"
        call_next = AsyncMock(return_value=MagicMock())

        result = await middleware.dispatch(request, call_next)
        call_next.assert_called_once()

    @pytest.mark.asyncio
    @patch("integrations.billing_middleware.get_usage")
    @patch("integrations.billing_middleware.get_plan")
    async def test_blocks_over_limit(self, mock_plan, mock_usage):
        """Returns 402 when task limit exceeded."""
        mock_usage.return_value = {"plan": "free", "tasks_used": 5}
        plan_obj = MagicMock()
        plan_obj.task_limit = 5
        plan_obj.name = "Free"
        mock_plan.return_value = plan_obj

        middleware = BillingMiddleware(app=MagicMock())
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/tasks"
        request.state.user_id = "test-user"
        call_next = AsyncMock()

        result = await middleware.dispatch(request, call_next)
        assert result.status_code == 402
        call_next.assert_not_called()


class TestIncrementUsage:
    """Test usage tracking after task completion."""

    @pytest.mark.asyncio
    @patch("integrations.stripe_billing.aioredis")
    async def test_increment_usage(self, mock_redis_module):
        """Increments task count and cost in Redis."""
        from integrations.stripe_billing import increment_usage

        mock_r = AsyncMock()
        mock_redis_module.from_url.return_value = mock_r

        await increment_usage("user-123", cost=0.05)

        # Verify Redis operations were called
        assert mock_r.incr.called or mock_r.incrby.called or mock_r.incrbyfloat.called


class TestGetPlan:
    """Test plan configuration lookup."""

    def test_known_plans(self):
        """All plan IDs return valid plan objects."""
        from integrations.stripe_billing import get_plan

        for plan_id in ["free", "starter", "pro", "team", "enterprise"]:
            plan = get_plan(plan_id)
            assert plan is not None
            assert plan.task_limit != 0  # Must have a limit (or -1 for unlimited)

    def test_unknown_plan_returns_free(self):
        """Unknown plan ID defaults to free tier."""
        from integrations.stripe_billing import get_plan

        plan = get_plan("nonexistent")
        assert plan.task_limit == 5 or plan.name.lower() == "free"

    def test_all_stripe_plans_match_db_constraint(self):
        """Verify plan IDs match DB constraint values."""
        from integrations.stripe_billing import PLANS

        valid_plans = {"free", "starter", "pro", "team", "enterprise"}
        for plan_id in PLANS:
            assert plan_id in valid_plans, f"Plan '{plan_id}' not in DB constraint"


class TestWebhookHandling:
    """Test Stripe webhook event processing."""

    @pytest.mark.asyncio
    @patch("integrations.stripe_billing.settings")
    async def test_checkout_completed_stores_plan(self, mock_settings):
        """Webhook checkout.session.completed stores plan in Redis."""
        mock_settings.stripe_secret_key = ""
        mock_settings.stripe_webhook_secret = ""
        mock_settings.redis_url = "redis://localhost:6379"

        mock_r = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_r):
            from integrations.stripe_billing import handle_webhook

            event = {
                "type": "checkout.session.completed",
                "data": {"object": {
                    "client_reference_id": "user-1",
                    "customer": "cus_abc123",
                    "metadata": {"plan_id": "pro"},
                }},
            }
            result = await handle_webhook(json.dumps(event).encode(), "")

        assert result["received"] is True
        assert result["type"] == "checkout.session.completed"
        mock_r.set.assert_called()

    @pytest.mark.asyncio
    @patch("integrations.stripe_billing.settings")
    async def test_unknown_event_still_acknowledged(self, mock_settings):
        """Unknown webhook events are acknowledged without error."""
        mock_settings.stripe_secret_key = ""
        mock_settings.stripe_webhook_secret = ""

        from integrations.stripe_billing import handle_webhook

        event = {"type": "unknown.event", "data": {"object": {}}}
        result = await handle_webhook(json.dumps(event).encode(), "")

        assert result["received"] is True
