"""Tests for SecureAgent SDK API — API keys, ingest, dashboard, tenant isolation.

Tests use in-memory SQLite via the shared conftest fixtures.
"""

import os

os.environ["TESTING"] = "1"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def setup():
    """Set up test DB, app client, and create a tenant + API key."""
    from api.main import app
    from db.database import get_db

    engine = create_async_engine("sqlite+aiosqlite:///", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create tenant
        resp = await client.post("/api/v1/keys/tenants", json={
            "name": "Test Corp",
            "plan": "cloud",
        })
        assert resp.status_code == 200
        tenant = resp.json()
        tenant_id = tenant["tenant_id"]

        # Create API key with all permissions
        async with session_factory() as db:
            from api.services.api_keys import create_api_key
            raw_key, api_key_record = await create_api_key(
                db,
                tenant_id=tenant_id,
                name="Test Key",
                permissions={"ingest": True, "dashboard": True},
            )

        yield {
            "client": client,
            "tenant_id": tenant_id,
            "raw_key": raw_key,
            "api_key_id": api_key_record.id,
            "session_factory": session_factory,
        }

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def setup_two_tenants():
    """Set up test DB with TWO tenants for isolation testing."""
    from api.main import app
    from db.database import get_db

    engine = create_async_engine("sqlite+aiosqlite:///", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create two tenants
        resp_a = await client.post("/api/v1/keys/tenants", json={"name": "Tenant A"})
        resp_b = await client.post("/api/v1/keys/tenants", json={"name": "Tenant B"})
        tenant_a = resp_a.json()["tenant_id"]
        tenant_b = resp_b.json()["tenant_id"]

        async with session_factory() as db:
            from api.services.api_keys import create_api_key
            key_a, _ = await create_api_key(db, tenant_a, "Key A", {"ingest": True, "dashboard": True})
            key_b, _ = await create_api_key(db, tenant_b, "Key B", {"ingest": True, "dashboard": True})

        yield {
            "client": client,
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "key_a": key_a,
            "key_b": key_b,
        }

    app.dependency_overrides.clear()
    await engine.dispose()


# ─── API Key Validation ──────────────────────────────────────────────────────

class TestApiKeyValidation:
    @pytest.mark.asyncio
    async def test_valid_api_key_accepted(self, setup):
        client = setup["client"]
        resp = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self, setup):
        client = setup["client"]
        resp = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": "Bearer sa_live_invalidkey12345678901234"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_auth_header_rejected(self, setup):
        client = setup["client"]
        resp = await client.get("/api/v1/dashboard/sessions")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_malformed_auth_header_rejected(self, setup):
        client = setup["client"]
        resp = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": "NotBearer something"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_permission_check_ingest(self, setup):
        """Key with ingest permission should access ingest endpoint."""
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test_event"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 1

    @pytest.mark.asyncio
    async def test_permission_denied_without_permission(self, setup):
        """Key without dashboard permission should be rejected at dashboard."""
        # Create a key with only ingest permission
        async with setup["session_factory"]() as db:
            from api.services.api_keys import create_api_key
            raw_key, _ = await create_api_key(
                db, setup["tenant_id"], "Ingest Only", {"ingest": True, "dashboard": False},
            )

        client = setup["client"]
        resp = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_revoked_key_rejected(self, setup):
        """Revoked API key should be rejected."""
        async with setup["session_factory"]() as db:
            from api.services.api_keys import create_api_key, revoke_api_key
            raw_key, api_key = await create_api_key(
                db, setup["tenant_id"], "Temp Key", {"ingest": True, "dashboard": True},
            )
            await revoke_api_key(db, api_key.id, setup["tenant_id"])

        client = setup["client"]
        resp = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 401


# ─── Ingest API ──────────────────────────────────────────────────────────────

class TestIngestAPI:
    @pytest.mark.asyncio
    async def test_ingest_single_event(self, setup):
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [
                {
                    "type": "tool_call",
                    "tool_name": "search_web",
                    "session_id": "sess_test_001",
                    "agent_id": "researcher",
                    "risk_level": "low",
                    "tokens_used": 500,
                    "cost": 0.01,
                },
            ]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 1
        assert data["batch_id"].startswith("batch_")

    @pytest.mark.asyncio
    async def test_ingest_batch(self, setup):
        client = setup["client"]
        events = [
            {"type": f"action_{i}", "session_id": "sess_batch", "agent_id": "coder"}
            for i in range(10)
        ]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": events},
        )
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 10

    @pytest.mark.asyncio
    async def test_ingest_max_batch_size(self, setup):
        """Batch with >100 events should be rejected by validation."""
        client = setup["client"]
        events = [{"type": f"evt_{i}"} for i in range(101)]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": events},
        )
        assert resp.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_ingest_empty_batch_rejected(self, setup):
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": []},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_ingest_invalid_tool_name_rejected(self, setup):
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test", "tool_name": "invalid tool name!@#"}]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_ingest_metadata_truncation(self, setup):
        """Large metadata should be truncated, not rejected."""
        client = setup["client"]
        large_metadata = {"key": "x" * 10_000}
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test", "metadata": large_metadata}]},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_ingest_health(self, setup):
        client = setup["client"]
        resp = await client.get("/api/v1/health/ingest")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ─── Dashboard API ───────────────────────────────────────────────────────────

class TestDashboardAPI:
    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, setup):
        client = setup["client"]
        resp = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    @pytest.mark.asyncio
    async def test_list_sessions_after_ingest(self, setup):
        client = setup["client"]
        auth = {"Authorization": f"Bearer {setup['raw_key']}"}

        # Ingest events into two sessions
        await client.post("/api/v1/ingest", headers=auth, json={"events": [
            {"type": "call1", "session_id": "sess_a"},
            {"type": "call2", "session_id": "sess_a"},
            {"type": "call3", "session_id": "sess_b"},
        ]})

        resp = await client.get("/api/v1/dashboard/sessions", headers=auth)
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 2
        session_ids = {s["session_id"] for s in sessions}
        assert "sess_a" in session_ids
        assert "sess_b" in session_ids

    @pytest.mark.asyncio
    async def test_list_events_for_session(self, setup):
        client = setup["client"]
        auth = {"Authorization": f"Bearer {setup['raw_key']}"}

        await client.post("/api/v1/ingest", headers=auth, json={"events": [
            {"type": "action_1", "session_id": "sess_events", "agent_id": "agent_a"},
            {"type": "action_2", "session_id": "sess_events", "agent_id": "agent_b"},
        ]})

        resp = await client.get(
            "/api/v1/dashboard/events",
            headers=auth,
            params={"session_id": "sess_events"},
        )
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_export_audit_trail(self, setup):
        client = setup["client"]
        auth = {"Authorization": f"Bearer {setup['raw_key']}"}

        await client.post("/api/v1/ingest", headers=auth, json={"events": [
            {"type": "tool_call", "session_id": "sess_export", "tool_name": "search"},
        ]})

        resp = await client.get(
            "/api/v1/dashboard/audit/export",
            headers=auth,
            params={"session_id": "sess_export"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess_export"
        assert data["total_events"] == 1
        assert len(data["events"]) == 1

    @pytest.mark.asyncio
    async def test_usage_stats(self, setup):
        client = setup["client"]
        auth = {"Authorization": f"Bearer {setup['raw_key']}"}

        await client.post("/api/v1/ingest", headers=auth, json={"events": [
            {"type": "call", "session_id": "sess_stats", "tokens_used": 1000, "cost": 0.05},
            {"type": "call", "session_id": "sess_stats", "tokens_used": 2000, "cost": 0.10},
        ]})

        resp = await client.get(
            "/api/v1/dashboard/stats",
            headers=auth,
            params={"session_id": "sess_stats"},
        )
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_events"] == 2
        assert stats["total_tokens"] == 3000
        assert abs(stats["total_cost"] - 0.15) < 0.01

    @pytest.mark.asyncio
    async def test_compliance_report(self, setup):
        client = setup["client"]
        auth = {"Authorization": f"Bearer {setup['raw_key']}"}

        await client.post("/api/v1/ingest", headers=auth, json={"events": [
            {"type": "tool_call", "session_id": "sess_compliance", "risk_level": "high"},
            {"type": "pii_detected", "session_id": "sess_compliance", "risk_level": "medium"},
            {"type": "taint_violation", "session_id": "sess_compliance", "risk_level": "high"},
        ]})

        resp = await client.get(
            "/api/v1/dashboard/compliance/report",
            headers=auth,
            params={"session_id": "sess_compliance"},
        )
        assert resp.status_code == 200
        report = resp.json()
        assert report["total_events"] == 3
        assert report["high_risk_events"] == 2
        assert report["pii_detections"] == 1
        assert report["taint_violations"] == 1


# ─── Tenant Isolation ────────────────────────────────────────────────────────

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_data(self, setup_two_tenants):
        s = setup_two_tenants
        client = s["client"]

        # Tenant A ingests data
        await client.post("/api/v1/ingest", json={"events": [
            {"type": "secret_action", "session_id": "sess_a_only"},
        ]}, headers={"Authorization": f"Bearer {s['key_a']}"})

        # Tenant B ingests data
        await client.post("/api/v1/ingest", json={"events": [
            {"type": "public_action", "session_id": "sess_b_only"},
        ]}, headers={"Authorization": f"Bearer {s['key_b']}"})

        # Tenant A lists sessions — should only see sess_a_only
        resp_a = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": f"Bearer {s['key_a']}"},
        )
        assert resp_a.status_code == 200
        sessions_a = {s["session_id"] for s in resp_a.json()["sessions"]}
        assert "sess_a_only" in sessions_a
        assert "sess_b_only" not in sessions_a

        # Tenant B lists sessions — should only see sess_b_only
        resp_b = await client.get(
            "/api/v1/dashboard/sessions",
            headers={"Authorization": f"Bearer {s['key_b']}"},
        )
        assert resp_b.status_code == 200
        sessions_b = {s["session_id"] for s in resp_b.json()["sessions"]}
        assert "sess_b_only" in sessions_b
        assert "sess_a_only" not in sessions_b

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_events(self, setup_two_tenants):
        s = setup_two_tenants
        client = s["client"]

        # Both tenants use same session_id (edge case)
        await client.post("/api/v1/ingest", json={"events": [
            {"type": "action_a", "session_id": "shared_sess"},
        ]}, headers={"Authorization": f"Bearer {s['key_a']}"})

        await client.post("/api/v1/ingest", json={"events": [
            {"type": "action_b", "session_id": "shared_sess"},
        ]}, headers={"Authorization": f"Bearer {s['key_b']}"})

        # Tenant A queries events — should only see action_a
        resp_a = await client.get(
            "/api/v1/dashboard/events",
            headers={"Authorization": f"Bearer {s['key_a']}"},
            params={"session_id": "shared_sess"},
        )
        events_a = resp_a.json()["events"]
        actions_a = {e["action"] for e in events_a}
        assert "action_a" in actions_a
        assert "action_b" not in actions_a

        # Tenant B queries events — should only see action_b
        resp_b = await client.get(
            "/api/v1/dashboard/events",
            headers={"Authorization": f"Bearer {s['key_b']}"},
            params={"session_id": "shared_sess"},
        )
        events_b = resp_b.json()["events"]
        actions_b = {e["action"] for e in events_b}
        assert "action_b" in actions_b
        assert "action_a" not in actions_b

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_export_tenant_b_audit(self, setup_two_tenants):
        s = setup_two_tenants
        client = s["client"]

        # Tenant B ingests data
        await client.post("/api/v1/ingest", json={"events": [
            {"type": "secret", "session_id": "sess_b_secret"},
        ]}, headers={"Authorization": f"Bearer {s['key_b']}"})

        # Tenant A tries to export Tenant B's session
        resp = await client.get(
            "/api/v1/dashboard/audit/export",
            headers={"Authorization": f"Bearer {s['key_a']}"},
            params={"session_id": "sess_b_secret"},
        )
        assert resp.status_code == 200
        # Should return empty — no access to Tenant B data
        assert resp.json()["total_events"] == 0

    @pytest.mark.asyncio
    async def test_stats_are_tenant_isolated(self, setup_two_tenants):
        s = setup_two_tenants
        client = s["client"]

        # Tenant A: 3 events with 3000 tokens
        await client.post("/api/v1/ingest", json={"events": [
            {"type": "call", "session_id": "s", "tokens_used": 1000, "cost": 0.05},
            {"type": "call", "session_id": "s", "tokens_used": 1000, "cost": 0.05},
            {"type": "call", "session_id": "s", "tokens_used": 1000, "cost": 0.05},
        ]}, headers={"Authorization": f"Bearer {s['key_a']}"})

        # Tenant B: 1 event with 500 tokens
        await client.post("/api/v1/ingest", json={"events": [
            {"type": "call", "session_id": "s", "tokens_used": 500, "cost": 0.01},
        ]}, headers={"Authorization": f"Bearer {s['key_b']}"})

        # Tenant A stats should show 3 events
        resp_a = await client.get("/api/v1/dashboard/stats", headers={
            "Authorization": f"Bearer {s['key_a']}"
        })
        assert resp_a.json()["total_events"] == 3
        assert resp_a.json()["total_tokens"] == 3000

        # Tenant B stats should show 1 event
        resp_b = await client.get("/api/v1/dashboard/stats", headers={
            "Authorization": f"Bearer {s['key_b']}"
        })
        assert resp_b.json()["total_events"] == 1
        assert resp_b.json()["total_tokens"] == 500


# ─── Input Validation ────────────────────────────────────────────────────────

class TestInputValidation:
    @pytest.mark.asyncio
    async def test_negative_tokens_rejected(self, setup):
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test", "tokens_used": -100}]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_excessive_tokens_rejected(self, setup):
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test", "tokens_used": 99_999_999}]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_cost_rejected(self, setup):
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test", "cost": -1.0}]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_risk_level_normalized(self, setup):
        """Invalid risk level should be normalized to 'low', not rejected."""
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test", "risk_level": "extreme"}]},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_session_id_length_limit(self, setup):
        """Session ID exceeding max_length should be rejected."""
        client = setup["client"]
        resp = await client.post(
            "/api/v1/ingest",
            headers={"Authorization": f"Bearer {setup['raw_key']}"},
            json={"events": [{"type": "test", "session_id": "x" * 200}]},
        )
        assert resp.status_code == 422
