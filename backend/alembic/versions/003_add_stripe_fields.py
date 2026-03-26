"""Add stripe_customer_id to tenants and fix plan constraint values.

Revision ID: 003_stripe_fields
Revises: 002_constraints
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

revision = "003_stripe_fields"
down_revision = "002_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add stripe_customer_id column
    op.add_column(
        "tenants",
        sa.Column("stripe_customer_id", sa.String(128), unique=True, nullable=True),
    )

    # Fix plan constraint (002 originally had 'free', 'cloud', 'enterprise')
    op.drop_constraint("ck_tenants_plan", "tenants")
    op.create_check_constraint(
        "ck_tenants_plan",
        "tenants",
        sa.text("plan IN ('free', 'starter', 'pro', 'team', 'enterprise')"),
    )


def downgrade() -> None:
    # Restore original constraint
    op.drop_constraint("ck_tenants_plan", "tenants")
    op.create_check_constraint(
        "ck_tenants_plan",
        "tenants",
        sa.text("plan IN ('free', 'cloud', 'enterprise')"),
    )

    # Remove stripe_customer_id column
    op.drop_column("tenants", "stripe_customer_id")
