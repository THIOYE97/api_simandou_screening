"""piste d'audit conformité (compliance_events) + décision sur opérations

Revision ID: m6b_compliance_audit
Revises: m1c_currencies
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "m6b_compliance_audit"
down_revision = "m1c_currencies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kyt_transactions", sa.Column("decision", sa.String(16), nullable=False, server_default="PENDING"))
    op.create_table(
        "compliance_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_kind", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("subject_label", sa.String(), nullable=True),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("to_status", sa.String(32), nullable=True),
        sa.Column("decision", sa.String(16), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_compliance_events_subject_id", "compliance_events", ["subject_id"])
    op.create_index("ix_compliance_events_alert_id", "compliance_events", ["alert_id"])
    op.create_index("ix_compliance_events_tenant_id", "compliance_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("compliance_events")
    op.drop_column("kyt_transactions", "decision")
