"""Add foreign keys, check constraints, and indexes for production integrity.

Revision ID: 002_constraints
Revises: 001_initial
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa

revision = "002_constraints"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Foreign keys ──

    # usage.task_id → tasks.id
    op.create_foreign_key(
        "fk_usage_task_id",
        "usage", "tasks",
        ["task_id"], ["id"],
        ondelete="CASCADE",
    )

    # usage.user_id → tenants.id (nullable)
    op.create_foreign_key(
        "fk_usage_user_id",
        "usage", "tenants",
        ["user_id"], ["id"],
        ondelete="SET NULL",
    )

    # api_keys.tenant_id → tenants.id
    op.create_foreign_key(
        "fk_api_keys_tenant_id",
        "api_keys", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE",
    )

    # audit_events.tenant_id → tenants.id
    op.create_foreign_key(
        "fk_audit_events_tenant_id",
        "audit_events", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE",
    )

    # tasks.user_id → tenants.id (nullable)
    op.create_foreign_key(
        "fk_tasks_user_id",
        "tasks", "tenants",
        ["user_id"], ["id"],
        ondelete="SET NULL",
    )

    # ── Check constraints ──

    # tasks.status must be valid
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        sa.text("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')"),
    )

    # tasks.budget_limit must be non-negative
    op.create_check_constraint(
        "ck_tasks_budget_limit",
        "tasks",
        sa.text("budget_limit IS NULL OR budget_limit >= 0"),
    )

    # tasks.estimated_cost must be non-negative
    op.create_check_constraint(
        "ck_tasks_estimated_cost",
        "tasks",
        sa.text("estimated_cost >= 0"),
    )

    # usage.cost must be non-negative
    op.create_check_constraint(
        "ck_usage_cost",
        "usage",
        sa.text("cost >= 0"),
    )

    # usage.input_tokens and output_tokens must be non-negative
    op.create_check_constraint(
        "ck_usage_tokens",
        "usage",
        sa.text("input_tokens >= 0 AND output_tokens >= 0"),
    )

    # tenants.plan must be valid
    op.create_check_constraint(
        "ck_tenants_plan",
        "tenants",
        sa.text("plan IN ('free', 'starter', 'pro', 'team', 'enterprise')"),
    )

    # audit_events.risk_level must be valid
    op.create_check_constraint(
        "ck_audit_events_risk_level",
        "audit_events",
        sa.text("risk_level IN ('low', 'medium', 'high', 'critical')"),
    )

    # agents.type must be valid
    op.create_check_constraint(
        "ck_agents_type",
        "agents",
        sa.text("type IN ('core', 'custom')"),
    )

    # ── Indexes for common queries ──

    op.create_index("ix_tasks_status_created", "tasks", ["status", "created_at"])
    op.create_index("ix_usage_task_created", "usage", ["task_id", "created_at"])
    op.create_index("ix_audit_events_tenant_ts", "audit_events", ["tenant_id", "timestamp"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_audit_events_tenant_ts")
    op.drop_index("ix_usage_task_created")
    op.drop_index("ix_tasks_status_created")

    # Drop check constraints
    op.drop_constraint("ck_agents_type", "agents")
    op.drop_constraint("ck_audit_events_risk_level", "audit_events")
    op.drop_constraint("ck_tenants_plan", "tenants")
    op.drop_constraint("ck_usage_tokens", "usage")
    op.drop_constraint("ck_usage_cost", "usage")
    op.drop_constraint("ck_tasks_estimated_cost", "tasks")
    op.drop_constraint("ck_tasks_budget_limit", "tasks")
    op.drop_constraint("ck_tasks_status", "tasks")

    # Drop foreign keys
    op.drop_constraint("fk_tasks_user_id", "tasks")
    op.drop_constraint("fk_audit_events_tenant_id", "audit_events")
    op.drop_constraint("fk_api_keys_tenant_id", "api_keys")
    op.drop_constraint("fk_usage_user_id", "usage")
    op.drop_constraint("fk_usage_task_id", "usage")
