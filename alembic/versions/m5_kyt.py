"""M5: KYT (kyt_transactions, kyt_sars)

Revision ID: m5_kyt
Revises: m6_alerting
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "m5_kyt"
down_revision = "m6_alerting"
branch_labels = None
depends_on = None

kyt_source_system = postgresql.ENUM("T24", "SWIFT", "ACH", "RTGS", "MANUAL", name="kyt_source_system")
kyt_direction = postgresql.ENUM("IN", "OUT", "INTERNAL", name="kyt_direction")
kyt_channel = postgresql.ENUM("CASH", "WIRE", "CHECK", "CARD", "OTHER", name="kyt_channel")
sar_status = postgresql.ENUM("DRAFT", "SUBMITTED", "UNDER_REVIEW", "DECIDED", name="sar_status")
sar_decision = postgresql.ENUM("PENDING", "FILED_TO_CENTIF", "DISMISSED", name="sar_decision")


def upgrade() -> None:
    bind = op.get_bind()
    for e in (kyt_source_system, kyt_direction, kyt_channel, sar_status, sar_decision):
        e.create(bind, checkfirst=True)

    op.create_table(
        "kyt_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_ref", sa.String(), nullable=True),
        sa.Column("source_system", postgresql.ENUM(name="kyt_source_system", create_type=False), nullable=False),
        sa.Column("direction", postgresql.ENUM(name="kyt_direction", create_type=False),
                  nullable=False, server_default="IN"),
        sa.Column("channel", postgresql.ENUM(name="kyt_channel", create_type=False),
                  nullable=False, server_default="WIRE"),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("customer_ref", sa.String(), nullable=True),
        sa.Column("counterparty_name", sa.String(), nullable=True),
        sa.Column("counterparty_country", sa.String(64), nullable=True),
        sa.Column("value_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("risk_assessment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_kyt_transactions_tenant_id", "kyt_transactions", ["tenant_id"])
    op.create_index("ix_kyt_transactions_external_ref", "kyt_transactions", ["external_ref"])
    op.create_index("ix_kyt_transactions_customer_ref", "kyt_transactions", ["customer_ref"])

    op.create_table(
        "kyt_sars",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_ref", sa.String(), nullable=True),
        sa.Column("subject_label", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("status", postgresql.ENUM(name="sar_status", create_type=False),
                  nullable=False, server_default="DRAFT"),
        sa.Column("decision", postgresql.ENUM(name="sar_decision", create_type=False),
                  nullable=False, server_default="PENDING"),
        sa.Column("related_alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_transaction_ids", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_kyt_sars_tenant_id", "kyt_sars", ["tenant_id"])
    op.create_index("ix_kyt_sars_subject_ref", "kyt_sars", ["subject_ref"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("kyt_sars")
    op.drop_table("kyt_transactions")
    for e in (sar_decision, sar_status, kyt_channel, kyt_direction, kyt_source_system):
        e.drop(bind, checkfirst=True)
