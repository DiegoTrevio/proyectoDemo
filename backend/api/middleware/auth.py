"""Authentication middleware — SuperTokens session + API key validation.

Two auth flows:
  1. Browser sessions: SuperTokens JWT in cookie/header (for frontend)
  2. SDK/API keys: Bearer token in Authorization header (for programmatic access)

Usage:
    @router.post("/tasks")
    async def create_task(
        user: AuthUser = Depends(require_auth),
        db: AsyncSession = Depends(get_db),
    ):
        # user.user_id, user.tenant_id, user.permissions available
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.database import get_db
from db.models import ApiKey, Tenant

logger = logging.getLogger("agentos.middleware.auth")


@dataclass
class AuthUser:
    """Authenticated user context available in route handlers."""
    user_id: str
    tenant_id: str
    auth_method: str  # "api_key" or "session"
    permissions: dict = field(default_factory=dict)
    key_id: Optional[str] = None


def _hash_key(raw_key: str) -> str:
    """Hash an API key for lookup. Must match the hash used at key creation."""
    import hashlib
    salted = f"{settings.api_key_salt}:{raw_key}"
    return hashlib.sha256(salted.encode()).hexdigest()


async def _authenticate_api_key(
    raw_key: str,
    db: AsyncSession,
) -> AuthUser:
    """Validate a Bearer API key against the database."""
    key_hash = _hash_key(raw_key)

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active == True,  # noqa: E712
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # Check expiration
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API key has expired")

    # Verify tenant is active
    tenant_result = await db.execute(
        select(Tenant).where(
            Tenant.id == api_key.tenant_id,
            Tenant.is_active == True,  # noqa: E712
        )
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant account is inactive")

    # Update last_used_at
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return AuthUser(
        user_id=api_key.tenant_id,
        tenant_id=api_key.tenant_id,
        auth_method="api_key",
        permissions=api_key.permissions or {},
        key_id=api_key.id,
    )


async def _authenticate_session(request: Request) -> Optional[AuthUser]:
    """Validate a SuperTokens session (JWT in cookie or Authorization header).

    Returns AuthUser if valid session exists, None otherwise.
    """
    try:
        # Try SuperTokens session verification
        from supertokens_python.recipe.session.asyncio import get_session

        session = await get_session(request, session_required=False)
        if session is None:
            return None

        user_id = session.get_user_id()
        # Access payload for tenant_id (set during login)
        payload = session.get_access_token_payload()
        tenant_id = payload.get("tenant_id", user_id)

        return AuthUser(
            user_id=user_id,
            tenant_id=tenant_id,
            auth_method="session",
            permissions=payload.get("permissions", {}),
        )
    except ImportError:
        logger.debug("SuperTokens not configured — session auth disabled")
        return None
    except Exception as e:
        logger.debug("Session validation failed: %s", e)
        return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthUser:
    """Extract and validate the authenticated user from the request.

    Tries API key first (Bearer token), then SuperTokens session.
    Raises 401 if neither is valid.
    """
    # 1. Check for Bearer API key
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:].startswith("sa_"):
        raw_key = auth_header[7:]
        return await _authenticate_api_key(raw_key, db)

    # 2. Check SuperTokens session
    session_user = await _authenticate_session(request)
    if session_user:
        return session_user

    # 3. No valid auth found
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide an API key (Bearer sa_...) or login via the dashboard.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Dependency aliases for routes
require_auth = get_current_user


async def require_permission(permission: str):
    """Factory for permission-checking dependencies.

    Usage:
        @router.post("/deploy")
        async def deploy(user: AuthUser = Depends(require_permission("deploy"))):
            ...
    """
    async def _check(user: AuthUser = Depends(require_auth)) -> AuthUser:
        # Wildcard permissions
        if user.permissions.get("*"):
            return user
        if not user.permissions.get(permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' required",
            )
        return user
    return _check


async def optional_auth(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[AuthUser]:
    """Like require_auth but returns None instead of raising 401.

    Use for endpoints that work with or without auth (e.g., /health).
    """
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None
