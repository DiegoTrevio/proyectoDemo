"""Shared test fixtures for AgentOS backend tests."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.middleware.auth import AuthUser
from db.models import Base


# ── Mock auth user for tests ─────────────────────────────────────────────

_TEST_USER = AuthUser(
    user_id="test-user",
    tenant_id="test-tenant",
    auth_method="test",
    permissions={"*": True},
)


async def _mock_require_auth():
    """Override require_auth to return a test user without real auth."""
    return _TEST_USER


# ── Database fixtures ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_engine():
    """Create a fresh in-memory SQLite engine per test."""
    engine = create_async_engine("sqlite+aiosqlite:///", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    """Yield an async database session for direct DB operations."""
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_engine):
    """Create an async test client with overridden DB, auth, and Redis dependencies."""
    from api.main import app
    from api.middleware.auth import require_auth
    from db.database import get_db

    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_auth] = _mock_require_auth

    # Mock arq pool so tasks are "enqueued" instead of running inline
    mock_arq = AsyncMock()
    mock_arq.enqueue_job = AsyncMock()
    app.state.arq_pool = mock_arq

    # Mock Redis so task creation/cancellation doesn't need a real Redis server
    mock_r = AsyncMock()
    mock_r.set = AsyncMock()
    mock_r.get = AsyncMock(return_value=None)
    mock_r.lpush = AsyncMock()
    mock_r.close = AsyncMock()
    mock_r.aclose = AsyncMock()

    with patch("redis.asyncio.from_url", return_value=mock_r):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()
    del app.state.arq_pool


@pytest.fixture
def sample_task_payload():
    """Reusable task creation payload."""
    return {
        "goal": "Test task for unit testing",
        "model": "claude-sonnet-4-20250514",
        "config": {"max_steps": 5},
    }


@pytest.fixture
def sample_agent_payload():
    """Reusable agent creation payload."""
    return {
        "name": "test-agent",
        "type": "custom",
        "system_prompt": "You are a test agent.",
        "tools": ["search", "code"],
        "model": "claude-sonnet-4-20250514",
    }
