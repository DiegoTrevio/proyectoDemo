"""Tests for AgentOS API endpoints.

Unit tests use an in-memory SQLite database via httpx AsyncClient.
Integration tests (marked @pytest.mark.integration) require running services.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """Create an async test client with a fresh in-memory database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from db.models import Base
    from db.database import get_db
    from api.main import app

    # Use SQLite for unit tests
    test_engine = create_async_engine("sqlite+aiosqlite:///", echo=False)
    test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()


# ─── Health ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ─── Tasks ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task(client: AsyncClient):
    resp = await client.post("/api/v1/tasks", json={"goal": "Write a hello world script"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "queued"
    assert "task_id" in data
    assert data["estimated_cost"] > 0


@pytest.mark.asyncio
async def test_get_task(client: AsyncClient):
    create = await client.post("/api/v1/tasks", json={"goal": "Test task"})
    task_id = create.json()["task_id"]
    resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["goal"] == "Test task"


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/tasks/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient):
    await client.post("/api/v1/tasks", json={"goal": "Task 1"})
    await client.post("/api/v1/tasks", json={"goal": "Task 2"})
    resp = await client.get("/api/v1/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["tasks"]) == 2


@pytest.mark.asyncio
async def test_cancel_task(client: AsyncClient):
    create = await client.post("/api/v1/tasks", json={"goal": "Cancel me"})
    task_id = create.json()["task_id"]
    resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_task_not_found(client: AsyncClient):
    resp = await client.delete("/api/v1/tasks/nonexistent")
    assert resp.status_code == 404


# ─── Agents ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient):
    resp = await client.get("/api/v1/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) >= 6  # 6 core agents
    names = [a["name"] for a in agents]
    assert "orchestrator" in names
    assert "coder" in names


@pytest.mark.asyncio
async def test_create_custom_agent(client: AsyncClient):
    resp = await client.post("/api/v1/agents", json={
        "name": "my-agent",
        "system_prompt": "You are a helpful assistant.",
        "tools": ["web_search"],
        "model": "agentOS/workhorse",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-agent"
    assert data["type"] == "custom"


@pytest.mark.asyncio
async def test_create_duplicate_agent(client: AsyncClient):
    payload = {"name": "dupe", "system_prompt": "Test", "tools": []}
    await client.post("/api/v1/agents", json=payload)
    resp = await client.post("/api/v1/agents", json=payload)
    assert resp.status_code == 409


# ─── Billing ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_billing_estimate(client: AsyncClient):
    resp = await client.get("/api/v1/billing/estimate", params={"goal": "Build a REST API"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["estimated_cost"] > 0
    assert data["model"]
    assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_billing_estimate_with_model(client: AsyncClient):
    resp = await client.get("/api/v1/billing/estimate", params={
        "goal": "Simple task",
        "model": "agentOS/cheap",
    })
    assert resp.status_code == 200
    assert resp.json()["model"] == "agentOS/cheap"


@pytest.mark.asyncio
async def test_billing_usage(client: AsyncClient):
    resp = await client.get("/api/v1/billing/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tokens"] == 0
    assert data["total_cost"] == 0


# ─── SSE Stream ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_endpoint_returns_event_stream(client: AsyncClient):
    """Verify the SSE endpoint returns the correct content-type."""
    resp = await client.get("/api/v1/tasks/test-id/stream", headers={"Accept": "text/event-stream"})
    assert resp.headers["content-type"].startswith("text/event-stream")


# ─── Memory (integration — requires Redis) ────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_store_and_retrieve(client: AsyncClient):
    resp = await client.post("/api/v1/memory", json={
        "namespace": "test-ns",
        "key": "greeting",
        "value": "hello world",
        "metadata": {"source": "test"},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["namespace"] == "test-ns"
    assert data["key"] == "greeting"

    resp = await client.get("/api/v1/memory/test-ns/greeting")
    assert resp.status_code == 200
    assert resp.json()["value"] == "hello world"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_list(client: AsyncClient):
    await client.post("/api/v1/memory", json={
        "namespace": "list-ns", "key": "k1", "value": "v1",
    })
    await client.post("/api/v1/memory", json={
        "namespace": "list-ns", "key": "k2", "value": "v2",
    })
    resp = await client.get("/api/v1/memory/list-ns")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_delete(client: AsyncClient):
    await client.post("/api/v1/memory", json={
        "namespace": "del-ns", "key": "temp", "value": "gone",
    })
    resp = await client.delete("/api/v1/memory/del-ns/temp")
    assert resp.status_code == 200

    resp = await client.get("/api/v1/memory/del-ns/temp")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/memory/nope/nope")
    assert resp.status_code == 404
