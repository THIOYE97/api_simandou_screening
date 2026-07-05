"""référentiel devises (ref_currencies)

Revision ID: m1c_currencies
Revises: m4b_adverse_media
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "m1c_currencies"
down_revision = "m4b_adverse_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ref_currencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(3), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ref_currencies_code", "ref_currencies", ["code"])


def downgrade() -> None:
    op.drop_table("ref_currencies")
