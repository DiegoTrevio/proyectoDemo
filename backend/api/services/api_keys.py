"""API Key Service — create, validate, and revoke SDK API keys.

Keys are generated as `sa_live_<32-char-hex>` and stored as SHA-256+salt hashes.
Only the hash is stored; the raw key is shown once at creation time.
"""

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, Tenant

logger = logging.getLogger("agentos.services.api_keys")

# Salt for key hashing (loaded from env or generated)
_KEY_SALT = os.environ.get("API_KEY_SALT", "secureagent-key-salt-v1")


def _hash_key(raw_key: str) -> str:
    """Hash an API key with salt using SHA-256."""
    salted = f"{_KEY_SALT}:{raw_key}"
    return hashlib.sha256(salted.encode()).hexdigest()


def _generate_raw_key() -> str:
    """Generate a new raw API key."""
    return f"sa_live_{uuid.uuid4().hex}"


async def create_tenant(db: AsyncSession, name: str, plan: str = "free") -> Tenant:
    """Create a new tenant."""
    tenant = Tenant(name=name, plan=plan)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    logger.info("Created tenant: %s (%s)", tenant.id, name)
    return tenant


async def create_api_key(
    db: AsyncSession,
    tenant_id: str,
    name: str = "Default Key",
    permissions: Optional[dict] = None,
) -> tuple[str, ApiKey]:
    """Create a new API key. Returns (raw_key, api_key_record).

    The raw key is returned only once — it cannot be retrieved later.
    """
    raw_key = _generate_raw_key()
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]  # "sa_live_xxxx" for display

    api_key = ApiKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        tenant_id=tenant_id,
        name=name,
        permissions=permissions or {"ingest": True, "dashboard": True},
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("Created API key %s for tenant %s", key_prefix, tenant_id)
    return raw_key, api_key


async def validate_api_key(db: AsyncSession, raw_key: str) -> Optional[ApiKey]:
    """Validate an API key and return the record if valid.

    Returns None if key is invalid, inactive, or expired.
    Updates last_used_at on successful validation.
    """
    if not raw_key or not raw_key.startswith("sa_live_"):
        return None

    key_hash = _hash_key(raw_key)
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active == True,
        )
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        return None

    # Check expiry
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        logger.warning("Expired API key used: %s", api_key.key_prefix)
        return None

    # Update last_used_at
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )
    await db.commit()

    return api_key


async def revoke_api_key(db: AsyncSession, key_id: str, tenant_id: str) -> bool:
    """Revoke an API key. Returns True if found and revoked."""
    result = await db.execute(
        update(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
        .values(is_active=False)
    )
    await db.commit()
    revoked = result.rowcount > 0
    if revoked:
        logger.info("Revoked API key %s", key_id)
    return revoked


async def list_api_keys(db: AsyncSession, tenant_id: str) -> list[dict]:
    """List all API keys for a tenant (without revealing the actual key)."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        {
            "id": k.id,
            "key_prefix": k.key_prefix + "..." ,
            "name": k.name,
            "permissions": k.permissions,
            "is_active": k.is_active,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat(),
        }
        for k in keys
    ]
