"""SecureAgent SDK — API Key Management.

Endpoints for creating, listing, and revoking API keys.
Protected by JWT auth (SuperTokens).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import AuthUser, require_auth
from api.services.api_keys import (
    create_api_key,
    create_tenant,
    list_api_keys,
    revoke_api_key,
)
from db.database import get_db

logger = logging.getLogger("agentos.api.api_keys")

router = APIRouter(prefix="/api/v1/keys", tags=["api-keys"])


# ─── Models ─────────────────────────────────────────────────────────────

class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    plan: str = Field(default="free", pattern=r"^(free|starter|pro|team|enterprise)$")


class CreateTenantResponse(BaseModel):
    tenant_id: str
    name: str
    plan: str


class CreateKeyRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=32)
    name: str = Field(default="Default Key", max_length=256)
    permissions: Optional[dict] = None


class CreateKeyResponse(BaseModel):
    raw_key: str  # Only shown once!
    key_id: str
    key_prefix: str
    name: str


class RevokeKeyRequest(BaseModel):
    key_id: str = Field(..., min_length=1, max_length=32)
    tenant_id: str = Field(..., min_length=1, max_length=32)


# ─── Routes ─────────────────────────────────────────────────────────────

@router.post("/tenants", response_model=CreateTenantResponse)
async def create_tenant_endpoint(
    request: CreateTenantRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new tenant organization."""
    tenant = await create_tenant(db, name=request.name, plan=request.plan)
    return CreateTenantResponse(
        tenant_id=tenant.id,
        name=tenant.name,
        plan=tenant.plan,
    )


@router.post("", response_model=CreateKeyResponse)
async def create_key_endpoint(
    request: CreateKeyRequest,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for a tenant.

    WARNING: The raw key is returned only once. Store it securely.
    """
    raw_key, api_key = await create_api_key(
        db,
        tenant_id=request.tenant_id,
        name=request.name,
        permissions=request.permissions,
    )
    return CreateKeyResponse(
        raw_key=raw_key,
        key_id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
    )


@router.get("")
async def list_keys_endpoint(
    tenant_id: str,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all API keys for a tenant (keys are not revealed)."""
    # Users can only list their own tenant's keys
    if tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot access another tenant's keys")
    keys = await list_api_keys(db, tenant_id=tenant_id)
    return {"keys": keys, "total": len(keys)}


@router.delete("")
async def revoke_key_endpoint(
    request: RevokeKeyRequest,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key."""
    # Users can only revoke their own tenant's keys
    if request.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot revoke another tenant's keys")
    revoked = await revoke_api_key(db, key_id=request.key_id, tenant_id=request.tenant_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked", "key_id": request.key_id}
