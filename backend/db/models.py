"""SQLAlchemy models for AgentOS."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Use JSONB on Postgres, fallback to JSON on SQLite/other
JSONB = PG_JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="ck_tasks_status"),
        CheckConstraint("budget_limit IS NULL OR budget_limit >= 0", name="ck_tasks_budget_limit"),
        CheckConstraint("estimated_cost >= 0", name="ck_tasks_estimated_cost"),
        Index("ix_tasks_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    model: Mapped[str | None] = mapped_column(String(128))
    config: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    artifacts: Mapped[list | None] = mapped_column(JSONB)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    budget_limit: Mapped[float | None] = mapped_column(Float)
    user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("type IN ('core', 'custom')", name="ck_agents_type"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="custom")
    system_prompt: Mapped[str | None] = mapped_column(Text)
    tools: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(128))
    is_core: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SecurityPolicy(Base):
    __tablename__ = "security_policies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    policy_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (
        CheckConstraint("cost >= 0", name="ck_usage_cost"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_usage_tokens"),
        Index("ix_usage_task_created", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ─── SecureAgent SDK Models ─────────────────────────────────────────────

class Tenant(Base):
    """Organization / customer account."""
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "plan IN ('free', 'starter', 'pro', 'team', 'enterprise')",
            name="ck_tenants_plan",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ApiKey(Base):
    """API key for SDK authentication."""
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # sa_live_xxxx for display
    tenant_id: Mapped[str] = mapped_column(String(32), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), default="Default Key")
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"ingest": true, "dashboard": true}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditEventDB(Base):
    """Persistent audit event from SDK."""
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("risk_level IN ('low', 'medium', 'high', 'critical')", name="ck_audit_events_risk_level"),
        Index("ix_audit_events_tenant_ts", "tenant_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(32), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    agent_id: Mapped[str] = mapped_column(String(128), default="default")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), default="")
    input_hash: Mapped[str] = mapped_column(String(128), default="")
    output_hash: Mapped[str] = mapped_column(String(128), default="")
    model_used: Mapped[str] = mapped_column(String(128), default="")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")  # low, medium, high, critical
    prev_hash: Mapped[str] = mapped_column(String(128), default="")
    event_hash: Mapped[str] = mapped_column(String(128), default="")
    signature: Mapped[str] = mapped_column(String(128), default="")
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    batch_id: Mapped[str | None] = mapped_column(String(64))
