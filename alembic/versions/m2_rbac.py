"""M2: RBAC (rbac_roles)

Revision ID: m2_rbac
Revises: m5_kyt
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "m2_rbac"
down_revision = "m5_kyt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rbac_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_rbac_roles_tenant_id", "rbac_roles", ["tenant_id"])
    op.create_index("ix_rbac_roles_code", "rbac_roles", ["code"])
    op.create_unique_constraint("uq_rbac_roles_tenant_code", "rbac_roles", ["tenant_id", "code"])

    op.create_table(
        "rbac_user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_code", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_rbac_user_roles_tenant_id", "rbac_user_roles", ["tenant_id"])
    op.create_index("ix_rbac_user_roles_user_id", "rbac_user_roles", ["user_id"])
    op.create_unique_constraint("uq_rbac_user_roles", "rbac_user_roles", ["tenant_id", "user_id", "role_code"])


def downgrade() -> None:
    op.drop_table("rbac_user_roles")
    op.drop_table("rbac_roles")
