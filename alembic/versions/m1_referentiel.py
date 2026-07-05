"""M1: référentiel (pays/GAFI, secteurs, catégories clients, scénarios de risque)

Revision ID: m1_referentiel
Revises: s3_refresh_tokens
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "m1_referentiel"
down_revision = "s3_refresh_tokens"
branch_labels = None
depends_on = None

scenario_category = postgresql.ENUM(
    "SANCTIONS", "PEP", "GEOGRAPHY", "TRANSACTION", "BEHAVIOR", "ADVERSE_MEDIA",
    name="scenario_category",
)
scenario_severity = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "CRITICAL",
    name="scenario_severity",
)


def upgrade() -> None:
    bind = op.get_bind()
    scenario_category.create(bind, checkfirst=True)
    scenario_severity.create(bind, checkfirst=True)

    op.create_table(
        "ref_countries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("iso_code", sa.String(3), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_high_risk", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_non_cooperative", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("risk_weight", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ref_countries_iso_code", "ref_countries", ["iso_code"])

    op.create_table(
        "ref_business_sectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("risk_weight", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ref_business_sectors_code", "ref_business_sectors", ["code"])

    op.create_table(
        "ref_client_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_risk_weight", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ref_client_categories_code", "ref_client_categories", ["code"])

    op.create_table(
        "ref_risk_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category",
                  postgresql.ENUM(name="scenario_category", create_type=False), nullable=False),
        sa.Column("severity",
                  postgresql.ENUM(name="scenario_severity", create_type=False),
                  nullable=False, server_default="MEDIUM"),
        sa.Column("criteria", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("risk_weight", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ref_risk_scenarios_code", "ref_risk_scenarios", ["code"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("ref_risk_scenarios")
    op.drop_table("ref_client_categories")
    op.drop_table("ref_business_sectors")
    op.drop_table("ref_countries")
    scenario_severity.drop(bind, checkfirst=True)
    scenario_category.drop(bind, checkfirst=True)
