"""Tests for the Skills Registry system."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from agents.skills.registry import SkillRegistry, SkillDefinition, SkillMatch


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def catalog_dir(tmp_path):
    """Create a temp catalog with test skills."""
    # Skill 1: TDD
    tdd_dir = tmp_path / "tdd"
    tdd_dir.mkdir()
    (tdd_dir / "SKILL.yaml").write_text("""
name: tdd
description: "Test-driven development"
version: "1.0"
agents: [coder, validator]
triggers:
  keywords:
    - \\bTDD\\b
    - \\btest.driven\\b
    - \\bwrite\\s+tests?\\s+first\\b
  task_types: [code]
tools: [e2b_sandbox]
complexity_hint: medium
tags: [testing]
instructions: |
  Follow Red/Green/Refactor cycle.
""")

    # Skill 2: API design
    api_dir = tmp_path / "api-design"
    api_dir.mkdir()
    (api_dir / "SKILL.yaml").write_text("""
name: api-design
description: "Design REST APIs"
version: "2.0"
agents: [coder]
triggers:
  keywords:
    - \\bAPI\\b
    - \\bREST\\b
    - \\bendpoint
  task_types: [code]
tools: []
complexity_hint: medium
tags: [api, backend]
instructions: |
  Use nouns for URLs, proper HTTP methods.
""")

    # Skill 3: Security
    sec_dir = tmp_path / "security"
    sec_dir.mkdir()
    (sec_dir / "SKILL.yaml").write_text("""
name: security-audit
description: "Audit code for vulnerabilities"
version: "1.0"
agents: [validator, coder, researcher]
triggers:
  keywords:
    - \\bsecurity\\b
    - \\bvulnerabilit
    - \\bOWASP\\b
  task_types: [code, research]
tools: [e2b_sandbox]
complexity_hint: complex
tags: [security]
instructions: |
  Check OWASP top 10.
""")

    return tmp_path


@pytest.fixture
def registry(catalog_dir):
    return SkillRegistry(catalog_dir=catalog_dir)


# ── Loading & Discovery ──────────────────────────────────────────────────

class TestSkillLoading:
    def test_loads_all_skills(self, registry):
        assert len(registry.list_skills()) == 3

    def test_skill_names(self, registry):
        names = registry.list_names()
        assert "tdd" in names
        assert "api-design" in names
        assert "security-audit" in names

    def test_skill_fields(self, registry):
        skill = registry.get("tdd")
        assert skill is not None
        assert skill.name == "tdd"
        assert skill.description == "Test-driven development"
        assert skill.version == "1.0"
        assert "coder" in skill.agents
        assert "validator" in skill.agents
        assert skill.complexity_hint == "medium"
        assert "testing" in skill.tags
        assert "Red/Green/Refactor" in skill.instructions

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None

    def test_empty_catalog(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        reg = SkillRegistry(catalog_dir=empty_dir)
        assert len(reg.list_skills()) == 0

    def test_nonexistent_catalog_dir(self, tmp_path):
        reg = SkillRegistry(catalog_dir=tmp_path / "does-not-exist")
        assert len(reg.list_skills()) == 0

    def test_skills_for_agent(self, registry):
        coder_skills = registry.skills_for_agent("coder")
        assert len(coder_skills) == 3  # tdd, api-design, security-audit all include coder

        validator_skills = registry.skills_for_agent("validator")
        assert len(validator_skills) == 2  # tdd, security-audit

        browser_skills = registry.skills_for_agent("browser")
        assert len(browser_skills) == 0


# ── Matching ──────────────────────────────────────────────────────────────

class TestSkillMatching:
    def test_matches_tdd_keywords(self, registry):
        matches = registry.match("I want to use TDD for this feature")
        assert len(matches) >= 1
        assert matches[0].skill.name == "tdd"
        assert matches[0].confidence > 0

    def test_matches_api_keywords(self, registry):
        matches = registry.match("design a REST API for user management")
        names = [m.skill.name for m in matches]
        assert "api-design" in names

    def test_matches_security_keywords(self, registry):
        matches = registry.match("run a security audit on the codebase")
        names = [m.skill.name for m in matches]
        assert "security-audit" in names

    def test_no_match_returns_empty(self, registry):
        matches = registry.match("make me a sandwich")
        assert len(matches) == 0

    def test_best_match(self, registry):
        match = registry.best_match("write tests first using TDD")
        assert match is not None
        assert match.skill.name == "tdd"

    def test_best_match_none(self, registry):
        match = registry.best_match("make me a sandwich")
        assert match is None

    def test_task_type_bonus(self, registry):
        # With matching task_type, confidence should be higher
        matches_with_type = registry.match("check security", task_type="code")
        matches_without = registry.match("check security", task_type="")

        if matches_with_type and matches_without:
            # Same skill but potentially higher confidence with type
            assert matches_with_type[0].confidence >= matches_without[0].confidence

    def test_top_k_limits_results(self, registry):
        matches = registry.match("security API TDD test", top_k=2)
        assert len(matches) <= 2

    def test_matched_triggers_populated(self, registry):
        matches = registry.match("use TDD and write tests first")
        assert len(matches) >= 1
        assert len(matches[0].matched_triggers) > 0


# ── Instruction Injection ─────────────────────────────────────────────────

class TestInstructionInjection:
    def test_get_instructions_for_matching_agent(self, registry):
        instructions = registry.get_instructions_for_task(
            goal="use TDD for the new feature",
            agent_name="coder",
        )
        assert "Active Skills" in instructions
        assert "Red/Green/Refactor" in instructions

    def test_instructions_filtered_by_agent(self, registry):
        # browser is not in any skill's agents list
        instructions = registry.get_instructions_for_task(
            goal="use TDD for the new feature",
            agent_name="browser",
        )
        assert instructions == ""

    def test_instructions_empty_for_no_match(self, registry):
        instructions = registry.get_instructions_for_task(
            goal="make me a sandwich",
            agent_name="coder",
        )
        assert instructions == ""

    def test_instructions_min_confidence(self, registry):
        # Very high confidence threshold should filter out weak matches
        instructions = registry.get_instructions_for_task(
            goal="maybe check security",
            agent_name="coder",
            min_confidence=0.99,
        )
        assert instructions == ""


# ── Orchestrator Helpers ──────────────────────────────────────────────────

class TestOrchestratorHelpers:
    def test_classification_hints(self, registry):
        hints = registry.get_skill_hints_for_classification()
        assert "tdd" in hints
        assert "api-design" in hints
        assert "security-audit" in hints

    def test_classification_hints_empty_registry(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        reg = SkillRegistry(catalog_dir=empty)
        assert reg.get_skill_hints_for_classification() == ""

    def test_suggest_agents(self, registry):
        agents = registry.suggest_agents_for_goal("write TDD tests")
        assert "coder" in agents
        assert "validator" in agents

    def test_suggest_agents_no_match(self, registry):
        agents = registry.suggest_agents_for_goal("make a sandwich")
        assert agents == []

    def test_suggest_agents_deduplicates(self, registry):
        # "security API" should match both security-audit and api-design
        # Both have "coder" — it should appear only once
        agents = registry.suggest_agents_for_goal("security audit of the API")
        assert agents.count("coder") <= 1


# ── Real Catalog ──────────────────────────────────────────────────────────

class TestRealCatalog:
    """Test with the actual skill catalog shipped with AgentOS."""

    def test_real_catalog_loads(self):
        """The production catalog should load without errors."""
        from agents.skills.registry import skill_registry
        skills = skill_registry.list_skills()
        assert len(skills) >= 8  # We ship 8 skills

    def test_real_catalog_all_skills_have_required_fields(self):
        from agents.skills.registry import skill_registry
        for skill in skill_registry.list_skills():
            assert skill.name, f"Skill missing name"
            assert skill.description, f"Skill {skill.name} missing description"
            assert skill.agents, f"Skill {skill.name} has no agents"
            assert skill.triggers, f"Skill {skill.name} has no triggers"
            assert skill.instructions, f"Skill {skill.name} has no instructions"

    def test_real_catalog_tdd_match(self):
        from agents.skills.registry import skill_registry
        match = skill_registry.best_match("implement this feature using TDD")
        assert match is not None
        assert match.skill.name == "test-driven-development"

    def test_real_catalog_debug_match(self):
        from agents.skills.registry import skill_registry
        match = skill_registry.best_match("debug this crashing function")
        assert match is not None
        assert match.skill.name == "systematic-debugging"

    def test_real_catalog_chart_match(self):
        from agents.skills.registry import skill_registry
        match = skill_registry.best_match("create a dashboard with charts")
        assert match is not None
        assert match.skill.name == "data-visualization"

    def test_real_catalog_security_match(self):
        from agents.skills.registry import skill_registry
        match = skill_registry.best_match("run OWASP security audit")
        assert match is not None
        assert match.skill.name == "security-audit"


# ── API Endpoints ─────────────────────────────────────────────────────────

class TestSkillsAPI:
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

    def test_list_skills(self, client):
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 8
        assert all("name" in s for s in data)
        assert all("description" in s for s in data)

    def test_get_skill(self, client):
        resp = client.get("/api/v1/skills/test-driven-development")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-driven-development"
        assert "instructions" in data
        assert data["instructions"] != ""

    def test_get_skill_not_found(self, client):
        resp = client.get("/api/v1/skills/nonexistent")
        assert resp.status_code == 404

    def test_match_skills(self, client):
        resp = client.get("/api/v1/skills/match", params={"goal": "debug this crash"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["skill"] == "systematic-debugging"
        assert data[0]["confidence"] > 0

    def test_match_no_results(self, client):
        resp = client.get("/api/v1/skills/match", params={"goal": "make a sandwich"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_instructions(self, client):
        resp = client.get("/api/v1/skills/test-driven-development/instructions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is True
        assert "Red/Green/Refactor" in data["instructions"]

    def test_get_instructions_incompatible_agent(self, client):
        resp = client.get("/api/v1/skills/test-driven-development/instructions", params={"agent": "browser"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is False
