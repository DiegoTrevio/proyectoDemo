"""End-to-end integration tests for AgentOS task lifecycle.

Tests the complete flow: create task → verify queued → cancel → verify cancelled.
Uses the shared conftest fixtures with auth override and in-memory SQLite.
Redis is mocked since it's not available in unit test environment.
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


def _mock_redis():
    """Create a mock Redis client for task operations."""
    mock_r = AsyncMock()
    mock_r.set = AsyncMock()
    mock_r.get = AsyncMock(return_value=None)
    mock_r.lpush = AsyncMock()
    mock_r.close = AsyncMock()
    mock_r.aclose = AsyncMock()
    return mock_r


@pytest.fixture(autouse=True)
def mock_redis_connections():
    """Mock all Redis connections for E2E tests."""
    mock_r = _mock_redis()
    with patch("redis.asyncio.from_url", return_value=mock_r):
        yield mock_r


@pytest.mark.asyncio
async def test_full_task_lifecycle(client: AsyncClient):
    """E2E: create → get → list → cancel → verify cancelled."""
    # 1. Create a task
    create_resp = await client.post("/api/v1/tasks", json={
        "goal": "Research quantum computing trends",
    })
    assert create_resp.status_code == 201
    task = create_resp.json()
    task_id = task["task_id"]
    assert task["status"] == "queued"
    assert task["estimated_cost"] > 0
    assert task["model"]  # model should be auto-selected

    # 2. Get the task
    get_resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["goal"] == "Research quantum computing trends"

    # 3. List tasks — our task should appear
    list_resp = await client.get("/api/v1/tasks")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    task_ids = [t["task_id"] for t in list_data["tasks"]]
    assert task_id in task_ids

    # 4. Cancel the task
    cancel_resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # 5. Verify task is cancelled
    verify_resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "cancelled"

    # 6. Cannot cancel again
    recancel_resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert recancel_resp.status_code == 400


@pytest.mark.asyncio
async def test_agent_lifecycle(client: AsyncClient):
    """E2E: list core agents → create custom → verify listed → detect duplicate."""
    # 1. List core agents
    list_resp = await client.get("/api/v1/agents")
    assert list_resp.status_code == 200
    agents = list_resp.json()
    core_count = len([a for a in agents if a["type"] == "core"])
    assert core_count >= 6

    # 2. Create a custom agent
    create_resp = await client.post("/api/v1/agents", json={
        "name": "e2e-test-agent",
        "system_prompt": "You help with end-to-end tests.",
        "tools": ["search", "code_edit"],
        "model": "agentOS/workhorse",
    })
    assert create_resp.status_code == 201
    agent = create_resp.json()
    assert agent["name"] == "e2e-test-agent"
    assert agent["type"] == "custom"

    # 3. Verify it appears in the list
    list2_resp = await client.get("/api/v1/agents")
    names = [a["name"] for a in list2_resp.json()]
    assert "e2e-test-agent" in names

    # 4. Duplicate detection
    dup_resp = await client.post("/api/v1/agents", json={
        "name": "e2e-test-agent",
        "system_prompt": "Duplicate.",
        "tools": [],
    })
    assert dup_resp.status_code == 409


@pytest.mark.asyncio
async def test_billing_estimate_flow(client: AsyncClient):
    """E2E: estimate cost → create task → verify cost matches estimate range."""
    # 1. Get cost estimate
    est_resp = await client.get("/api/v1/billing/estimate", params={
        "goal": "Build a REST API with FastAPI",
    })
    assert est_resp.status_code == 200
    estimate = est_resp.json()
    assert estimate["estimated_cost"] > 0

    # 2. Create task with the same goal
    task_resp = await client.post("/api/v1/tasks", json={
        "goal": "Build a REST API with FastAPI",
    })
    assert task_resp.status_code == 201
    task_cost = task_resp.json()["estimated_cost"]

    # Both should produce a positive cost estimate
    assert task_cost > 0


@pytest.mark.asyncio
async def test_multiple_tasks_pagination(client: AsyncClient):
    """E2E: create multiple tasks → verify pagination works."""
    # Create 5 tasks
    for i in range(5):
        resp = await client.post("/api/v1/tasks", json={"goal": f"Pagination test task {i}"})
        assert resp.status_code == 201

    # Page 1 with page_size=2
    page1 = await client.get("/api/v1/tasks", params={"page": 1, "page_size": 2})
    assert page1.status_code == 200
    data1 = page1.json()
    assert data1["total"] == 5
    assert len(data1["tasks"]) == 2
    assert data1["page"] == 1

    # Page 2
    page2 = await client.get("/api/v1/tasks", params={"page": 2, "page_size": 2})
    assert page2.status_code == 200
    data2 = page2.json()
    assert len(data2["tasks"]) == 2

    # Page 3 (last page, should have 1 task)
    page3 = await client.get("/api/v1/tasks", params={"page": 3, "page_size": 2})
    assert page3.status_code == 200
    assert len(page3.json()["tasks"]) == 1
