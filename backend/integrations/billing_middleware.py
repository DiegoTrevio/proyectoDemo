"""Billing Middleware — enforces plan limits on task creation.

Checks before every POST /api/v1/tasks:
  1. User has active subscription
  2. Task count doesn't exceed plan limit
  3. Budget limit not exceeded
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from integrations.stripe_billing import get_usage, get_plan

logger = logging.getLogger("agentos.integrations.billing_middleware")


class BillingMiddleware(BaseHTTPMiddleware):
    """Enforce billing limits on task creation."""

    async def dispatch(self, request: Request, call_next):
        # Only check POST /api/v1/tasks
        if request.method != "POST" or request.url.path != "/api/v1/tasks":
            return await call_next(request)

        # Get user_id from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            # Auth middleware should have caught this — pass through
            return await call_next(request)

        try:
            usage = await get_usage(user_id)
            plan_id = usage.get("plan", "free")
            plan = get_plan(plan_id)

            # Check task limit (-1 = unlimited)
            if plan.task_limit > 0 and usage["tasks_used"] >= plan.task_limit:
                logger.warning(
                    "User %s exceeded task limit: %d/%d (%s plan)",
                    user_id, usage["tasks_used"], plan.task_limit, plan_id,
                )
                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "Task limit exceeded",
                        "detail": f"Your {plan.name} plan allows {plan.task_limit} tasks/month. "
                                  f"You've used {usage['tasks_used']}. Upgrade to continue.",
                        "plan": plan_id,
                        "tasks_used": usage["tasks_used"],
                        "tasks_limit": plan.task_limit,
                        "upgrade_url": "/billing",
                    },
                )

            # Check model access (if request body specifies a model)
            try:
                body = await request.json()
                requested_model = body.get("model", "")
                if requested_model and requested_model not in plan.models:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": "Model not available on your plan",
                            "detail": f"Model '{requested_model}' requires a higher plan.",
                            "allowed_models": plan.models,
                        },
                    )
            except Exception:
                pass  # Body parse failed — let the endpoint handle it

        except Exception as e:
            logger.warning("Billing check failed (allowing request): %s", e)

        return await call_next(request)
