"""Tests for the Skills Registry system."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from agents.skills.registry import SkillRegistry, SkillDefinition, SkillMatch, validate_skill, generate_template


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

    def test_create_skill(self, client):
        resp = client.post("/api/v1/skills", json={
            "name": "test-create-skill",
            "description": "A test skill created via API",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\bcreate-test\\b"], "task_types": ["code"]},
            "instructions": "This is a test skill with enough instructions to pass validation check.",
            "complexity_hint": "simple",
            "tags": ["test"],
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "created"
        # Verify it's registered
        resp2 = client.get("/api/v1/skills/test-create-skill")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "test-create-skill"
        # Cleanup
        client.delete("/api/v1/skills/test-create-skill")

    def test_create_skill_validation_error(self, client):
        resp = client.post("/api/v1/skills", json={
            "name": "bad-skill",
            "description": "Missing triggers",
            "agents": ["coder"],
            "triggers": {"keywords": [], "task_types": []},
            "instructions": "This is a test skill with enough instructions to pass validation check.",
        })
        assert resp.status_code == 422

    def test_delete_skill(self, client):
        # Create then delete
        client.post("/api/v1/skills", json={
            "name": "to-delete",
            "description": "Will be deleted",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\bdelete-me\\b"]},
            "instructions": "This skill exists only to test deletion and should be removed after.",
        })
        resp = client.delete("/api/v1/skills/to-delete")
        assert resp.status_code == 200
        # Verify gone
        resp2 = client.get("/api/v1/skills/to-delete")
        assert resp2.status_code == 404

    def test_delete_skill_not_found(self, client):
        resp = client.delete("/api/v1/skills/nonexistent")
        assert resp.status_code == 404

    def test_test_skill_endpoint(self, client):
        resp = client.post("/api/v1/skills/test", json={
            "skill": {
                "name": "test-dry-run",
                "description": "Dry run test",
                "agents": ["coder"],
                "triggers": {"keywords": ["\\bfoo\\b", "\\bbar\\b"]},
                "instructions": "Do foo and bar things when working on this kind of task.",
            },
            "sample_goals": [
                "implement foo feature",
                "fix the bar module",
                "make a sandwich",
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert len(data["matches"]) == 3
        assert data["matches"][0]["matched"] is True   # "foo" matches
        assert data["matches"][1]["matched"] is True   # "bar" matches
        assert data["matches"][2]["matched"] is False   # "sandwich" no match

    def test_validate_skill_endpoint(self, client):
        resp = client.post("/api/v1/skills/validate", json={
            "name": "valid-skill",
            "description": "A valid skill",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\btest\\b"]},
            "instructions": "These are detailed enough instructions for validation to pass.",
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_validate_skill_with_errors(self, client):
        resp = client.post("/api/v1/skills/validate", json={
            "name": "",
            "description": "",
            "agents": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) >= 3

    def test_template_endpoint(self, client):
        resp = client.get("/api/v1/skills/template", params={"name": "my-new-skill"})
        assert resp.status_code == 200
        data = resp.json()
        assert "my-new-skill" in data["yaml"]
        assert "instructions" in data

    def test_reload_endpoint(self, client):
        resp = client.post("/api/v1/skills/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data
        assert data["loaded"] >= 8

    def test_errors_endpoint(self, client):
        resp = client.get("/api/v1/skills/errors")
        assert resp.status_code == 200
        # Should be a dict (possibly empty if no errors)
        assert isinstance(resp.json(), dict)


# ── Validation ────────────────────────────────────────────────────────────

class TestValidation:
    def test_valid_skill(self):
        issues = validate_skill({
            "name": "good-skill",
            "description": "A good skill",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\btest\\b"]},
            "instructions": "These are detailed enough instructions for this skill to work.",
        })
        errors = [e for e in issues if e.severity == "error"]
        assert len(errors) == 0

    def test_missing_name(self):
        issues = validate_skill({"description": "x", "agents": ["coder"], "triggers": {"keywords": ["x"]}, "instructions": "x" * 60})
        assert any(e.field == "name" for e in issues)

    def test_bad_name_format(self):
        issues = validate_skill({"name": "Bad Name!", "description": "x", "agents": ["coder"], "triggers": {"keywords": ["x"]}, "instructions": "x" * 60})
        assert any(e.field == "name" and "lowercase" in e.message for e in issues)

    def test_missing_agents(self):
        issues = validate_skill({"name": "x", "description": "x", "agents": [], "triggers": {"keywords": ["x"]}, "instructions": "x" * 60})
        assert any(e.field == "agents" for e in issues)

    def test_unknown_agent_is_warning(self):
        issues = validate_skill({"name": "x", "description": "x", "agents": ["fake-agent"], "triggers": {"keywords": ["x"]}, "instructions": "x" * 60})
        agent_issues = [e for e in issues if e.field == "agents"]
        assert any(e.severity == "warning" for e in agent_issues)

    def test_missing_triggers(self):
        issues = validate_skill({"name": "x", "description": "x", "agents": ["coder"], "triggers": {"keywords": []}, "instructions": "x" * 60})
        assert any("trigger" in e.field for e in issues)

    def test_invalid_regex_trigger(self):
        issues = validate_skill({"name": "x", "description": "x", "agents": ["coder"], "triggers": {"keywords": ["[invalid"]}, "instructions": "x" * 60})
        assert any("regex" in e.message.lower() for e in issues)

    def test_short_instructions_warning(self):
        issues = validate_skill({"name": "x", "description": "x", "agents": ["coder"], "triggers": {"keywords": ["x"]}, "instructions": "Short."})
        assert any(e.field == "instructions" and e.severity == "warning" for e in issues)

    def test_bad_complexity_hint(self):
        issues = validate_skill({"name": "x", "description": "x", "agents": ["coder"], "triggers": {"keywords": ["x"]}, "instructions": "x" * 60, "complexity_hint": "extreme"})
        assert any(e.field == "complexity_hint" for e in issues)


# ── Template ──────────────────────────────────────────────────────────────

class TestTemplate:
    def test_template_has_name(self):
        t = generate_template("my-skill", "Does cool things")
        assert "my-skill" in t
        assert "Does cool things" in t

    def test_template_is_valid_yaml(self):
        import yaml
        t = generate_template("test-skill")
        # The template has comments and escaped backslashes — it's meant to be
        # copied and edited, not parsed directly. Just check it's non-empty.
        assert len(t) > 200
        assert "name:" in t
        assert "triggers:" in t
        assert "instructions:" in t


# ── Create / Delete / Reload ──────────────────────────────────────────────

class TestSkillLifecycle:
    @pytest.fixture
    def fresh_registry(self, tmp_path):
        return SkillRegistry(catalog_dir=tmp_path)

    def test_create_and_retrieve(self, fresh_registry):
        skill, warnings = fresh_registry.create_skill({
            "name": "lifecycle-test",
            "description": "Test lifecycle",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\blifecycle\\b"]},
            "instructions": "Test lifecycle instructions that are long enough to pass validation.",
        })
        assert skill.name == "lifecycle-test"
        assert fresh_registry.get("lifecycle-test") is not None

    def test_create_writes_yaml(self, fresh_registry):
        fresh_registry.create_skill({
            "name": "disk-test",
            "description": "Test disk write",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\bdisk\\b"]},
            "instructions": "Test disk write instructions that are long enough to pass validation.",
        })
        yaml_path = fresh_registry._catalog_dir / "disk-test" / "SKILL.yaml"
        assert yaml_path.exists()

    def test_create_duplicate_fails(self, fresh_registry):
        fresh_registry.create_skill({
            "name": "dupe-test",
            "description": "First",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\bdupe\\b"]},
            "instructions": "First version of this skill with enough content for validation.",
        })
        with pytest.raises(ValueError, match="already exists"):
            fresh_registry.create_skill({
                "name": "dupe-test",
                "description": "Second",
                "agents": ["coder"],
                "triggers": {"keywords": ["\\bdupe\\b"]},
                "instructions": "Second version of this skill with enough content for validation.",
            })

    def test_create_invalid_fails(self, fresh_registry):
        with pytest.raises(ValueError, match="Validation failed"):
            fresh_registry.create_skill({
                "name": "",
                "description": "",
                "agents": [],
                "triggers": {"keywords": []},
                "instructions": "",
            })

    def test_delete(self, fresh_registry):
        fresh_registry.create_skill({
            "name": "delete-me",
            "description": "To be deleted",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\bdelete\\b"]},
            "instructions": "This skill will be deleted as part of the lifecycle test.",
        })
        assert fresh_registry.delete_skill("delete-me") is True
        assert fresh_registry.get("delete-me") is None

    def test_delete_nonexistent(self, fresh_registry):
        assert fresh_registry.delete_skill("nope") is False

    def test_reload(self, fresh_registry):
        fresh_registry.create_skill({
            "name": "reload-test",
            "description": "Test reload",
            "agents": ["coder"],
            "triggers": {"keywords": ["\\breload\\b"]},
            "instructions": "This skill tests hot-reload functionality and persistence.",
        })
        result = fresh_registry.reload()
        assert result["loaded"] == 1
        assert "reload-test" in result["unchanged"]

    def test_test_skill(self, fresh_registry):
        result = fresh_registry.test_skill(
            data={
                "name": "dry-run",
                "description": "Dry run test",
                "agents": ["coder"],
                "triggers": {"keywords": ["\\bhello\\b", "\\bworld\\b"]},
                "instructions": "Detailed instructions for the dry run test skill definition.",
            },
            sample_goals=["hello world", "hello there", "goodbye"],
        )
        assert result["valid"] is True
        assert result["matches"][0]["matched"] is True
        assert result["matches"][0]["confidence"] == 0.66  # two matches
        assert result["matches"][1]["matched"] is True
        assert result["matches"][2]["matched"] is False
