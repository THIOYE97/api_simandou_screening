"""adverse media (adverse_media_records)

Revision ID: m4b_adverse_media
Revises: m2_rbac
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "m4b_adverse_media"
down_revision = "m2_rbac"
branch_labels = None
depends_on = None

adverse_media_category = postgresql.ENUM(
    "FRAUD", "CORRUPTION", "MONEY_LAUNDERING", "TERRORISM", "TRAFFICKING",
    "SANCTIONS_EVASION", "ORGANIZED_CRIME", "OTHER",
    name="adverse_media_category",
)


def upgrade() -> None:
    bind = op.get_bind()
    adverse_media_category.create(bind, checkfirst=True)
    op.create_table(
        "adverse_media_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("category", postgresql.ENUM(name="adverse_media_category", create_type=False), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_adverse_media_normalized_name", "adverse_media_records", ["normalized_name"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("adverse_media_records")
    adverse_media_category.drop(bind, checkfirst=True)
