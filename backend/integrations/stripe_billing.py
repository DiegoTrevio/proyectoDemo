"""Stripe Billing — subscription management and usage metering.

Plans:
  Free:       $0/mo   — 5 tasks, Sonnet only
  Starter:    $29/mo  — 100 tasks, 10 SaaS integrations
  Pro:        $79/mo  — 500 tasks, everything, voice
  Team:       $199/mo — 2000 tasks, RBAC, API
  Enterprise: $999+   — unlimited, on-premise, SOC2
"""

import logging
from dataclasses import dataclass

from config.settings import settings

logger = logging.getLogger("agentos.integrations.billing")


# ── Plan configuration ───────────────────────────────────────────────────

@dataclass(frozen=True)
class PlanConfig:
    name: str
    price_monthly: int      # cents
    task_limit: int         # per month, -1 = unlimited
    saas_integrations: int  # max connected apps
    models: list[str]       # allowed model families
    features: frozenset[str]


PLANS: dict[str, PlanConfig] = {
    "free": PlanConfig(
        name="Free", price_monthly=0, task_limit=5,
        saas_integrations=0, models=["agentOS/workhorse"],
        features=frozenset({"basic_tasks"}),
    ),
    "starter": PlanConfig(
        name="Starter", price_monthly=2900, task_limit=100,
        saas_integrations=10, models=["agentOS/workhorse", "agentOS/workhorse-gemini"],
        features=frozenset({"basic_tasks", "saas_integrations"}),
    ),
    "pro": PlanConfig(
        name="Pro", price_monthly=7900, task_limit=500,
        saas_integrations=-1, models=["agentOS/workhorse", "agentOS/workhorse-gemini",
                                       "agentOS/workhorse-qwen", "agentOS/workhorse-kimi",
                                       "agentOS/orchestrator"],
        features=frozenset({"basic_tasks", "saas_integrations", "voice", "all_models"}),
    ),
    "team": PlanConfig(
        name="Team", price_monthly=19900, task_limit=2000,
        saas_integrations=-1, models=["agentOS/workhorse", "agentOS/workhorse-gemini",
                                       "agentOS/workhorse-qwen", "agentOS/workhorse-kimi",
                                       "agentOS/orchestrator"],
        features=frozenset({"basic_tasks", "saas_integrations", "voice", "all_models", "rbac", "api"}),
    ),
    "enterprise": PlanConfig(
        name="Enterprise", price_monthly=99900, task_limit=-1,
        saas_integrations=-1, models=["agentOS/workhorse", "agentOS/workhorse-gemini",
                                       "agentOS/workhorse-qwen", "agentOS/workhorse-kimi",
                                       "agentOS/orchestrator"],
        features=frozenset({"basic_tasks", "saas_integrations", "voice", "all_models",
                            "rbac", "api", "on_premise", "soc2", "hipaa"}),
    ),
}


def get_plan(plan_id: str) -> PlanConfig:
    return PLANS.get(plan_id, PLANS["free"])


# ── Stripe client ────────────────────────────────────────────────────────

def _get_stripe():
    """Lazy-load Stripe client."""
    import stripe
    stripe.api_key = settings.stripe_secret_key
    return stripe


# ── Checkout & Portal ────────────────────────────────────────────────────

async def create_checkout_session(
    plan_id: str,
    user_id: str,
    success_url: str = "http://localhost:3000/billing/success",
    cancel_url: str = "http://localhost:3000/billing/cancel",
) -> dict:
    """Create a Stripe Checkout session for plan subscription."""
    stripe = _get_stripe()
    plan = get_plan(plan_id)

    if plan.price_monthly == 0:
        return {"url": success_url, "plan": "free"}

    # Price IDs would be created in Stripe Dashboard
    # For now, create a dynamic price
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"AgentOS {plan.name}"},
                    "unit_amount": plan.price_monthly,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            client_reference_id=user_id,
            metadata={"plan_id": plan_id, "user_id": user_id},
        )
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        logger.error("Checkout session creation failed: %s", e)
        return {"error": str(e)}


async def create_portal_session(customer_id: str) -> dict:
    """Create a Stripe Customer Portal session (manage subscription)."""
    stripe = _get_stripe()
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url="http://localhost:3000/settings",
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Portal session creation failed: %s", e)
        return {"error": str(e)}


# ── Usage metering ───────────────────────────────────────────────────────

async def record_task_usage(
    task_id: str,
    user_id: str,
    cost_usd: float,
    model_used: str,
    total_tokens: int,
) -> bool:
    """Record a completed task for usage-based billing."""
    stripe = _get_stripe()
    try:
        stripe.billing.MeterEvent.create(
            event_name="agentOS_task",
            payload={
                "stripe_customer_id": user_id,  # In prod, map user_id to Stripe customer
                "task_id": task_id,
                "cost_usd": str(cost_usd),
                "model": model_used,
                "tokens": str(total_tokens),
            },
        )
        logger.info("Recorded task usage: task=%s cost=$%.4f", task_id, cost_usd)
        return True
    except Exception as e:
        logger.warning("Failed to record usage (non-critical): %s", e)
        return False


# ── Usage queries ────────────────────────────────────────────────────────

async def get_usage(user_id: str) -> dict:
    """Get current billing usage for a user."""
    # In production, this queries Stripe + local DB
    # For now, return from Redis/local state
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            tasks_used = await r.get(f"billing:{user_id}:tasks_this_month") or "0"
            cost_total = await r.get(f"billing:{user_id}:cost_this_month") or "0.0"
            plan_id = await r.get(f"billing:{user_id}:plan") or "free"
        finally:
            await r.close()

        plan = get_plan(plan_id)
        return {
            "plan": plan_id,
            "plan_name": plan.name,
            "tasks_used": int(tasks_used),
            "tasks_limit": plan.task_limit,
            "cost_this_month": float(cost_total),
            "models_allowed": plan.models,
        }
    except Exception as e:
        logger.warning("Usage query failed: %s", e)
        return {"plan": "free", "tasks_used": 0, "tasks_limit": 5, "cost_this_month": 0.0}


async def increment_usage(user_id: str, cost: float) -> None:
    """Increment task count and cost for the current month."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.incr(f"billing:{user_id}:tasks_this_month")
            await r.incrbyfloat(f"billing:{user_id}:cost_this_month", cost)
            # Set TTL to end of month (roughly 31 days)
            await r.expire(f"billing:{user_id}:tasks_this_month", 2678400)
            await r.expire(f"billing:{user_id}:cost_this_month", 2678400)
        finally:
            await r.close()
    except Exception as e:
        logger.warning("Usage increment failed: %s", e)


# ── Webhook handler ──────────────────────────────────────────────────────

async def handle_webhook(payload: bytes, signature: str) -> dict:
    """Handle Stripe webhook events."""
    stripe = _get_stripe()
    webhook_secret = settings.stripe_webhook_secret

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
        else:
            import json
            event = json.loads(payload)
    except Exception as e:
        logger.error("Webhook verification failed: %s", e)
        return {"error": "Invalid signature"}

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        user_id = data.get("client_reference_id", "")
        plan_id = data.get("metadata", {}).get("plan_id", "starter")
        logger.info("Subscription created: user=%s plan=%s", user_id, plan_id)

        # Store plan in Redis
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                await r.set(f"billing:{user_id}:plan", plan_id)
            finally:
                await r.close()
        except Exception as e:
            logger.warning("Failed to store plan: %s", e)

    elif event_type == "customer.subscription.updated":
        logger.info("Subscription updated: %s", data.get("id"))

    elif event_type == "customer.subscription.deleted":
        logger.info("Subscription cancelled: %s", data.get("id"))

    elif event_type == "invoice.payment_failed":
        logger.warning("Payment failed for: %s", data.get("customer"))

    return {"received": True, "type": event_type}


# ── FastAPI router ───────────────────────────────────────────────────────

def create_billing_router():
    """Create FastAPI router for billing endpoints."""
    from fastapi import APIRouter, Request, HTTPException

    router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

    @router.post("/create-checkout-session")
    async def checkout(request: Request):
        data = await request.json()
        plan_id = data.get("plan_id", "starter")
        user_id = data.get("user_id", "")
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")
        result = await create_checkout_session(plan_id, user_id)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result

    @router.post("/webhook")
    async def webhook(request: Request):
        payload = await request.body()
        signature = request.headers.get("Stripe-Signature", "")
        return await handle_webhook(payload, signature)

    @router.get("/portal")
    async def portal(customer_id: str):
        result = await create_portal_session(customer_id)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result

    @router.get("/usage")
    async def usage(user_id: str):
        return await get_usage(user_id)

    return router
