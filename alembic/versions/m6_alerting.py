"""M6: alerting (alert_rules, alerts)

Revision ID: m6_alerting
Revises: m7_scoring
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "m6_alerting"
down_revision = "m7_scoring"
branch_labels = None
depends_on = None

alert_source = postgresql.ENUM("SCREENING", "SCORING", "KYT", "MANUAL", name="alert_source")
alert_severity = postgresql.ENUM("LOW", "MEDIUM", "HIGH", "CRITICAL", name="alert_severity")
alert_status = postgresql.ENUM(
    "OPEN", "IN_REVIEW", "ESCALATED", "CLOSED_TRUE_POSITIVE", "CLOSED_FALSE_POSITIVE",
    name="alert_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    alert_source.create(bind, checkfirst=True)
    alert_severity.create(bind, checkfirst=True)
    alert_status.create(bind, checkfirst=True)

    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", postgresql.ENUM(name="alert_source", create_type=False),
                  nullable=False, server_default="SCORING"),
        sa.Column("severity", postgresql.ENUM(name="alert_severity", create_type=False),
                  nullable=False, server_default="MEDIUM"),
        sa.Column("condition", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("auto_escalate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_alert_rules_code", "alert_rules", ["code"])

    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", postgresql.ENUM(name="alert_source", create_type=False), nullable=False),
        sa.Column("severity", postgresql.ENUM(name="alert_severity", create_type=False),
                  nullable=False, server_default="MEDIUM"),
        sa.Column("status", postgresql.ENUM(name="alert_status", create_type=False),
                  nullable=False, server_default="OPEN"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("rule_code", sa.String(), nullable=True),
        sa.Column("subject_ref", sa.String(), nullable=True),
        sa.Column("subject_label", sa.String(), nullable=True),
        sa.Column("risk_assessment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_alerts_tenant_id", "alerts", ["tenant_id"])
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_subject_ref", "alerts", ["subject_ref"])
    op.create_index("ix_alerts_rule_code", "alerts", ["rule_code"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("alerts")
    op.drop_table("alert_rules")
    alert_status.drop(bind, checkfirst=True)
    alert_severity.drop(bind, checkfirst=True)
    alert_source.drop(bind, checkfirst=True)
