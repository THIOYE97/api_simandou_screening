"""M7: scoring (risk_assessments)

Revision ID: m7_scoring
Revises: m1_referentiel
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "m7_scoring"
down_revision = "m1_referentiel"
branch_labels = None
depends_on = None

risk_subject_type = postgresql.ENUM("PERSON", "COMPANY", "TRANSACTION", name="risk_subject_type")
risk_class = postgresql.ENUM("LOW", "MEDIUM", "HIGH", "CRITICAL", name="risk_class")


def upgrade() -> None:
    bind = op.get_bind()
    risk_subject_type.create(bind, checkfirst=True)
    risk_class.create(bind, checkfirst=True)

    op.create_table(
        "risk_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type",
                  postgresql.ENUM(name="risk_subject_type", create_type=False), nullable=False),
        sa.Column("subject_ref", sa.String(), nullable=True),
        sa.Column("subject_label", sa.String(), nullable=True),
        sa.Column("total_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("risk_class",
                  postgresql.ENUM(name="risk_class", create_type=False),
                  nullable=False, server_default="LOW"),
        sa.Column("triggered", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_risk_assessments_tenant_id", "risk_assessments", ["tenant_id"])
    op.create_index("ix_risk_assessments_subject_ref", "risk_assessments", ["subject_ref"])
    op.create_index("ix_risk_assessments_created_at", "risk_assessments", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("risk_assessments")
    risk_class.drop(bind, checkfirst=True)
    risk_subject_type.drop(bind, checkfirst=True)
