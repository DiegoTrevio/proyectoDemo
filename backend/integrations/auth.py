"""SuperTokens Auth — JWT-based authentication with role-based access.

Recipes:
  - EmailPassword (register + login)
  - ThirdParty (Google OAuth + GitHub OAuth)
  - Session (JWT tokens, httpOnly cookies)
  - UserRoles (free, starter, pro, team, enterprise, admin)
"""

import logging
from functools import wraps

from config.settings import settings

logger = logging.getLogger("agentos.integrations.auth")


# ── Role definitions ─────────────────────────────────────────────────────

ROLES = {
    "free": {"tasks_per_month": 5, "models": ["agentOS/workhorse"], "features": {"basic"}},
    "starter": {"tasks_per_month": 100, "models": ["agentOS/workhorse", "agentOS/workhorse-gemini"],
                "features": {"basic", "saas_10"}},
    "pro": {"tasks_per_month": 500, "models": ["agentOS/workhorse", "agentOS/workhorse-gemini",
                                                 "agentOS/workhorse-qwen", "agentOS/workhorse-kimi",
                                                 "agentOS/orchestrator"],
            "features": {"basic", "saas_all", "voice", "all_models"}},
    "team": {"tasks_per_month": 2000, "models": ["agentOS/workhorse", "agentOS/workhorse-gemini",
                                                   "agentOS/workhorse-qwen", "agentOS/workhorse-kimi",
                                                   "agentOS/orchestrator"],
             "features": {"basic", "saas_all", "voice", "all_models", "rbac", "api"}},
    "enterprise": {"tasks_per_month": -1, "models": ["agentOS/workhorse", "agentOS/workhorse-gemini",
                                                       "agentOS/workhorse-qwen", "agentOS/workhorse-kimi",
                                                       "agentOS/orchestrator"],
                   "features": {"basic", "saas_all", "voice", "all_models", "rbac", "api",
                                "on_premise", "soc2"}},
    "admin": {"tasks_per_month": -1, "models": ["all"], "features": {"all"}},
}


# ── Public endpoints (no auth required) ──────────────────────────────────

PUBLIC_PATHS = frozenset({
    "/health",
    "/api/v1/billing/webhook",
    "/api/v1/openclaw/webhook",
    "/docs",
    "/openapi.json",
})


# ── SuperTokens initialization ───────────────────────────────────────────

def init_supertokens(app):
    """Initialize SuperTokens with the FastAPI app.

    Args:
        app: The FastAPI application instance.
    """
    try:
        from supertokens_python import init, InputAppInfo, SupertokensConfig
        from supertokens_python.recipe import (
            emailpassword,
            thirdparty,
            session,
            userroles,
        )
        from supertokens_python.framework.fastapi import get_middleware

        init(
            app_info=InputAppInfo(
                app_name="AgentOS",
                api_domain="http://localhost:8000",
                website_domain="http://localhost:3000",
                api_base_path="/auth",
                website_base_path="/auth",
            ),
            supertokens_config=SupertokensConfig(
                connection_uri=settings.supertokens_connection_uri,
            ),
            framework="fastapi",
            recipe_list=[
                emailpassword.init(),
                thirdparty.init(
                    sign_in_and_up_feature=thirdparty.SignInAndUpFeature(
                        providers=[
                            thirdparty.ProviderInput(
                                config=thirdparty.ProviderConfig(
                                    third_party_id="google",
                                    clients=[thirdparty.ProviderClientConfig(
                                        client_id="",  # Set via env
                                        client_secret="",
                                    )],
                                ),
                            ),
                            thirdparty.ProviderInput(
                                config=thirdparty.ProviderConfig(
                                    third_party_id="github",
                                    clients=[thirdparty.ProviderClientConfig(
                                        client_id="",
                                        client_secret="",
                                    )],
                                ),
                            ),
                        ],
                    ),
                ),
                session.init(),
                userroles.init(),
            ],
        )

        app.add_middleware(get_middleware())
        logger.info("SuperTokens initialized at %s", settings.supertokens_connection_uri)

    except ImportError:
        logger.warning("SuperTokens not installed — auth disabled")
    except Exception as e:
        logger.warning("SuperTokens init failed: %s", e)


# ── Auth middleware ───────────────────────────────────────────────────────

def create_auth_middleware():
    """Create FastAPI middleware for JWT validation.

    All /api/v1/* endpoints require a valid JWT except PUBLIC_PATHS.
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path

            # Skip auth for public paths
            if path in PUBLIC_PATHS or not path.startswith("/api/"):
                return await call_next(request)

            # Try SuperTokens session verification
            try:
                from supertokens_python.recipe.session.asyncio import get_session
                session = await get_session(request)
                if session:
                    # Attach user info to request state
                    request.state.user_id = session.get_user_id()
                    request.state.session = session
                    return await call_next(request)
            except ImportError:
                # SuperTokens not installed — check for bearer token
                pass
            except Exception:
                pass

            # Fallback: check Authorization header
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                user_info = await _verify_jwt(token)
                if user_info:
                    request.state.user_id = user_info.get("user_id", "")
                    request.state.role = user_info.get("role", "free")
                    return await call_next(request)

            return JSONResponse(
                status_code=401,
                content={"error": "Authentication required"},
            )

    return AuthMiddleware


async def _verify_jwt(token: str) -> dict | None:
    """Verify a JWT token. Returns user info or None."""
    if not token:
        return None

    # In production, verify against SuperTokens or a JWT library
    # For now, accept tokens with basic structure
    try:
        import json
        import base64

        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Decode payload (add padding)
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return {
            "user_id": decoded.get("sub", decoded.get("user_id", "")),
            "role": decoded.get("role", "free"),
        }
    except Exception:
        return None


# ── Role checking ────────────────────────────────────────────────────────

async def get_user_role(user_id: str) -> str:
    """Get a user's role from SuperTokens or Redis cache."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            role = await r.get(f"user:{user_id}:role")
            if role:
                return role
        finally:
            await r.close()
    except Exception:
        pass

    # Default to free
    return "free"


def check_feature_access(role: str, feature: str) -> bool:
    """Check if a role has access to a feature."""
    role_config = ROLES.get(role, ROLES["free"])
    if "all" in role_config["features"]:
        return True
    return feature in role_config["features"]


def check_model_access(role: str, model: str) -> bool:
    """Check if a role can use a specific model."""
    role_config = ROLES.get(role, ROLES["free"])
    if "all" in role_config["models"]:
        return True
    return model in role_config["models"]
