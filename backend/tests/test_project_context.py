"""Tests for Project Context — structured project memory + drift detection."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from memory.project_context import (
    ProjectContext,
    DriftReport,
    DriftIssue,
    SECTION_TYPES,
    _ROUTING_TABLE,
)
from memory.openviking_layer import openviking


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_openviking():
    """Clear OpenViking store before each test."""
    openviking._fallback_store.clear()
    yield
    openviking._fallback_store.clear()


@pytest.fixture
def ctx():
    return ProjectContext(project_id="test-project")


@pytest.fixture
def populated_ctx(ctx):
    """A context with all sections populated."""
    ctx.store_section("architecture", "Monolith with 3 services: API, worker, frontend.")
    ctx.store_section("stack", "Python 3.12, FastAPI, PostgreSQL, Redis, Next.js 14.")
    ctx.store_section("conventions", "snake_case for Python, camelCase for TypeScript.")
    ctx.store_section("decisions", "ADR-001: Chose PostgreSQL over MySQL for JSONB support.")
    ctx.store_section("setup", "docker compose up -d to start all services.")
    return ctx


# ── Section CRUD ──────────────────────────────────────────────────────────

class TestSectionCRUD:
    def test_store_and_retrieve(self, ctx):
        ctx.store_section("architecture", "Microservices with event bus.")
        content = ctx.get_section("architecture", tier=2)
        assert "Microservices" in content

    def test_store_generates_l0_summary(self, ctx):
        long_text = "A" * 1000
        ctx.store_section("stack", long_text)
        l0 = ctx.get_section("stack", tier=0)
        assert len(l0) < len(long_text)

    def test_invalid_section_raises(self, ctx):
        with pytest.raises(ValueError, match="Invalid section"):
            ctx.store_section("invalid_section", "content")

    def test_get_nonexistent_returns_none(self, ctx):
        assert ctx.get_section("architecture") is None

    def test_get_all_sections(self, populated_ctx):
        sections = populated_ctx.get_all_sections(tier=0)
        assert len(sections) == 5
        assert "architecture" in sections
        assert "stack" in sections

    def test_delete_section(self, ctx):
        ctx.store_section("setup", "Run make dev")
        assert ctx.get_section("setup") is not None
        assert ctx.delete_section("setup") is True
        assert ctx.get_section("setup") is None

    def test_delete_nonexistent(self, ctx):
        assert ctx.delete_section("setup") is False

    def test_metadata_stored(self, ctx):
        ctx.store_section("stack", "Python 3.12", metadata={"source": "manual"})
        entry = openviking._fallback_store.get(ctx._path("stack"))
        assert entry.metadata["source"] == "manual"
        assert entry.metadata["section_type"] == "stack"


# ── Routing ───────────────────────────────────────────────────────────────

class TestRouting:
    def test_routes_design_to_architecture(self, ctx):
        sections = ctx.route_for_task("redesign the system architecture")
        assert "architecture" in sections

    def test_routes_dependency_to_stack(self, ctx):
        sections = ctx.route_for_task("upgrade the dependency versions")
        assert "stack" in sections

    def test_routes_naming_to_conventions(self, ctx):
        sections = ctx.route_for_task("fix naming convention in auth module")
        assert "conventions" in sections

    def test_routes_deploy_to_setup(self, ctx):
        sections = ctx.route_for_task("deploy the application to production")
        assert "setup" in sections

    def test_routes_adr_to_decisions(self, ctx):
        sections = ctx.route_for_task("document the ADR for choosing Redis")
        assert "decisions" in sections

    def test_multi_keyword_scores_higher(self, ctx):
        sections = ctx.route_for_task("migrate the framework and refactor the design")
        # "migrate" → stack, architecture, decisions
        # "refactor" → architecture, conventions
        # "design" → architecture
        # architecture should be first (highest score)
        assert sections[0] == "architecture"

    def test_unknown_task_defaults(self, ctx):
        sections = ctx.route_for_task("do something completely random")
        assert sections == ["architecture", "conventions"]

    def test_get_context_for_task(self, populated_ctx):
        context = populated_ctx.get_context_for_task("fix naming convention")
        assert "conventions" in context.lower() or "snake_case" in context

    def test_get_context_empty_project(self, ctx):
        context = ctx.get_context_for_task("anything")
        assert context == ""


# ── Drift Detection ───────────────────────────────────────────────────────

class TestDriftDetection:
    def test_empty_project_has_warnings(self, ctx):
        report = ctx.check_drift()
        assert report.score < 100
        assert any(i.code == "MISSING_SECTION" for i in report.issues)

    def test_fully_populated_is_healthy(self, populated_ctx):
        report = populated_ctx.check_drift()
        assert report.healthy
        assert report.score >= 70

    def test_empty_section_is_error(self, ctx):
        ctx.store_section("architecture", "")
        report = ctx.check_drift()
        assert any(i.code == "EMPTY_SECTION" for i in report.issues)
        error_issues = [i for i in report.issues if i.code == "EMPTY_SECTION"]
        assert error_issues[0].severity == "error"

    def test_stale_section_detected(self, ctx):
        ctx.store_section("stack", "Python 3.12")
        # Manually set updated_at to 60 days ago
        entry = openviking._fallback_store[ctx._path("stack")]
        from datetime import datetime, timezone, timedelta
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        entry.metadata["updated_at"] = old_date
        report = ctx.check_drift()
        assert any(i.code == "STALE_SECTION" for i in report.issues)

    def test_low_coverage_warning(self, ctx):
        ctx.store_section("architecture", "Some content")
        report = ctx.check_drift()
        assert any(i.code == "LOW_COVERAGE" for i in report.issues)

    def test_file_references_detected(self, ctx):
        ctx.store_section("architecture", "Main entry point is src/api/main.py and config/settings.py")
        report = ctx.check_drift()
        assert any(i.code == "FILE_REFERENCES" for i in report.issues)

    def test_version_references_detected(self, ctx):
        versions = " ".join([f'"1.{i}.0"' for i in range(10)])
        ctx.store_section("stack", f"Dependencies: {versions}")
        report = ctx.check_drift()
        assert any(i.code == "MANY_VERSIONS" for i in report.issues)

    def test_score_never_below_zero(self, ctx):
        # Store many empty sections to rack up penalties
        for s in SECTION_TYPES:
            ctx.store_section(s, "")
        report = ctx.check_drift()
        assert report.score >= 0

    def test_drift_report_checked_at(self, ctx):
        report = ctx.check_drift()
        assert report.checked_at != ""


# ── Bulk Operations ───────────────────────────────────────────────────────

class TestBulkOperations:
    def test_populate_from_analysis(self, ctx):
        analysis = {
            "architecture": "Event-driven microservices",
            "stack": "Go 1.22, gRPC, PostgreSQL",
            "conventions": "camelCase everywhere",
        }
        paths = ctx.populate_from_analysis(analysis)
        assert len(paths) == 3
        assert ctx.get_section("architecture", tier=2) == "Event-driven microservices"

    def test_populate_ignores_invalid_sections(self, ctx):
        analysis = {"architecture": "Valid", "invalid_key": "Ignored", "": "Empty key"}
        paths = ctx.populate_from_analysis(analysis)
        assert len(paths) == 1

    def test_populate_ignores_empty_content(self, ctx):
        analysis = {"architecture": "", "stack": "   "}
        paths = ctx.populate_from_analysis(analysis)
        assert len(paths) == 0

    def test_export_scaffold(self, populated_ctx):
        scaffold = populated_ctx.export_scaffold()
        assert scaffold["project_id"] == "test-project"
        assert len(scaffold["sections"]) == 5
        assert "architecture" in scaffold["sections"]
        assert scaffold["sections"]["architecture"]["content"] is not None
        assert scaffold["drift"]["score"] >= 70
        assert scaffold["drift"]["healthy"] is True

    def test_export_empty_scaffold(self, ctx):
        scaffold = ctx.export_scaffold()
        assert len(scaffold["sections"]) == 0
        assert scaffold["drift"]["score"] < 100


# ── Memory Manager Integration ────────────────────────────────────────────

class TestManagerIntegration:
    @pytest.fixture(autouse=True)
    def mock_external_layers(self):
        """Mock all external memory layers to isolate project context testing."""
        with patch("memory.manager.supermemory_client") as mock_sm, \
             patch("memory.manager.mem0") as mock_m0, \
             patch("memory.manager.graphiti") as mock_gr:
            mock_sm.available = False
            mock_m0.search_memory.return_value = []
            mock_gr.query_facts = AsyncMock(return_value=[])
            yield

    @pytest.fixture(autouse=True)
    def mock_redis_session(self):
        with patch("memory.redis_session.set_task_state", new_callable=AsyncMock):
            yield

    @pytest.mark.asyncio
    async def test_gather_context_includes_project(self, populated_ctx):
        from memory.manager import gather_context
        # project_context singleton is shared — populated_ctx stored to same openviking
        # but with project_id="test-project", so we need to patch the singleton
        with patch("memory.manager.project_context", populated_ctx):
            result = await gather_context("fix naming conventions", user_id="u1")
            assert result["project_context"] != ""
            assert "Project Context" in result["combined"]

    @pytest.mark.asyncio
    async def test_gather_context_empty_project(self):
        from memory.manager import gather_context
        empty_ctx = ProjectContext(project_id="empty")
        with patch("memory.manager.project_context", empty_ctx):
            result = await gather_context("anything", user_id="u1")
            assert result["project_context"] == ""

    @pytest.mark.asyncio
    async def test_save_learnings_updates_decisions(self, populated_ctx):
        from memory.manager import save_learnings
        with patch("memory.manager.project_context", populated_ctx), \
             patch("memory.manager.supermemory_client") as mock_sm, \
             patch("memory.manager.graphiti") as mock_gr:
            mock_sm.available = False
            mock_gr.add_fact = AsyncMock()
            status = await save_learnings(
                goal="choose cache",
                result="Redis chosen",
                task_id="t1",
                facts=[{"subject": "team", "predicate": "decided", "object": "use Redis for caching"}],
            )
            assert status["project_context"] is True
            decisions = populated_ctx.get_section("decisions", tier=2)
            assert "Redis" in decisions


# ── API Endpoints ─────────────────────────────────────────────────────────

class TestProjectAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        from api.routes.tasks import require_auth

        async def _mock_auth():
            return {"tenant_id": "test", "plan": "starter"}

        app.dependency_overrides[require_auth] = _mock_auth
        yield TestClient(app)
        app.dependency_overrides.clear()

    @pytest.fixture(autouse=True)
    def mock_arq(self):
        from api.main import app
        mock = AsyncMock()
        mock.enqueue_job = AsyncMock()
        app.state.arq_pool = mock
        yield
        if hasattr(app.state, "arq_pool"):
            del app.state.arq_pool

    def test_store_section(self, client):
        resp = client.post("/api/v1/project/sections", json={
            "section": "architecture",
            "content": "Three-tier architecture with REST API.",
        })
        assert resp.status_code == 201
        assert resp.json()["section"] == "architecture"

    def test_get_section(self, client):
        client.post("/api/v1/project/sections", json={
            "section": "stack",
            "content": "Python 3.12, FastAPI",
        })
        resp = client.get("/api/v1/project/sections/stack")
        assert resp.status_code == 200
        assert "Python" in resp.json()["content"]

    def test_get_section_not_found(self, client):
        resp = client.get("/api/v1/project/sections/decisions")
        assert resp.status_code == 404

    def test_get_section_invalid(self, client):
        resp = client.get("/api/v1/project/sections/invalid")
        assert resp.status_code == 400

    def test_list_sections(self, client):
        client.post("/api/v1/project/sections", json={
            "section": "architecture", "content": "Monolith"
        })
        client.post("/api/v1/project/sections", json={
            "section": "stack", "content": "Python"
        })
        resp = client.get("/api/v1/project/sections")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_delete_section(self, client):
        client.post("/api/v1/project/sections", json={
            "section": "setup", "content": "Run make dev"
        })
        resp = client.delete("/api/v1/project/sections/setup")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_drift_endpoint(self, client):
        resp = client.get("/api/v1/project/drift")
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert "healthy" in data
        assert "issues" in data

    def test_scaffold_export(self, client):
        client.post("/api/v1/project/sections", json={
            "section": "architecture", "content": "Event-driven"
        })
        resp = client.get("/api/v1/project/scaffold")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        assert "drift" in data

    def test_route_preview(self, client):
        client.post("/api/v1/project/sections", json={
            "section": "conventions", "content": "Use snake_case"
        })
        resp = client.get("/api/v1/project/route", params={"goal": "fix naming convention"})
        assert resp.status_code == 200
        data = resp.json()
        assert "conventions" in data["routed_sections"]

    def test_populate_bulk(self, client):
        resp = client.post("/api/v1/project/populate", json={
            "architecture": "Microservices",
            "stack": "Go + gRPC",
        })
        assert resp.status_code == 200
        assert resp.json()["sections_stored"] == 2
