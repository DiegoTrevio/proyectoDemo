"""Add routing_mode column to tasks table.

Phase 2: Tracks whether a task was routed via Hermes-first or full orchestrator.

Revision ID: 004_task_routing_mode
Revises: 003_stripe_fields
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision = "004_task_routing_mode"
down_revision = "003_stripe_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("routing_mode", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "routing_mode")
