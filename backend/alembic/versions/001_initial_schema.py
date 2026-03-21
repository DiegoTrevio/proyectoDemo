"""Initial schema — all AgentOS tables.

Revision ID: 001_initial
Revises:
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tasks ---
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", index=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("artifacts", JSONB, nullable=True),
        sa.Column("estimated_cost", sa.Float, server_default="0.0"),
        sa.Column("budget_limit", sa.Float, nullable=True),
        sa.Column("user_id", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- agents ---
    op.create_table(
        "agents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), unique=True, nullable=False),
        sa.Column("type", sa.String(32), server_default="custom"),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("tools", JSONB, server_default="[]"),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("is_core", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- security_policies ---
    op.create_table(
        "security_policies",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("client_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("policy_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- usage ---
    op.create_table(
        "usage",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(32), index=True),
        sa.Column("user_id", sa.String(64), nullable=True, index=True),
        sa.Column("model", sa.String(128)),
        sa.Column("input_tokens", sa.Integer, server_default="0"),
        sa.Column("output_tokens", sa.Integer, server_default="0"),
        sa.Column("cost", sa.Float, server_default="0.0"),
        sa.Column("duration_ms", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- tenants ---
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("plan", sa.String(32), server_default="free"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- api_keys ---
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("key_hash", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, index=True),
        sa.Column("name", sa.String(256), server_default="Default Key"),
        sa.Column("permissions", JSONB, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- audit_events ---
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(128), nullable=False, index=True),
        sa.Column("session_id", sa.String(128), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(32), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("agent_id", sa.String(128), server_default="default"),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(128), server_default=""),
        sa.Column("input_hash", sa.String(128), server_default=""),
        sa.Column("output_hash", sa.String(128), server_default=""),
        sa.Column("model_used", sa.String(128), server_default=""),
        sa.Column("tokens_used", sa.Integer, server_default="0"),
        sa.Column("cost", sa.Float, server_default="0.0"),
        sa.Column("risk_level", sa.String(16), server_default="low"),
        sa.Column("prev_hash", sa.String(128), server_default=""),
        sa.Column("event_hash", sa.String(128), server_default=""),
        sa.Column("signature", sa.String(128), server_default=""),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("batch_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("api_keys")
    op.drop_table("tenants")
    op.drop_table("usage")
    op.drop_table("security_policies")
    op.drop_table("agents")
    op.drop_table("tasks")
