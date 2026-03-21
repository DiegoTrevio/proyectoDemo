"""Shared test fixtures for AgentOS backend tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base


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
    """Create an async test client with overridden DB dependency."""
    from api.main import app
    from db.database import get_db

    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


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
