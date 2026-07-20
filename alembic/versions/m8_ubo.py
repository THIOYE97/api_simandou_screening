"""m8: registre des bénéficiaires effectifs.

Revision ID: m8_ubo
Revises: m6g_reclassify_alerts
Create Date: 2026-07-20

Crée le registre interne des bénéficiaires effectifs (déclarations + chaînes de
détention) et ajoute la valeur d'origine d'alerte « UBO », afin que la
Conformité distingue une alerte portant sur un bénéficiaire effectif d'une
vérification client ou d'une opération.

NB : ALTER TYPE ... ADD VALUE est autorisé dans une transaction sur
PostgreSQL >= 12 tant que la valeur n'est pas UTILISÉE dans la même
transaction — ce qui est le cas ici (usage à l'exécution seulement).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "m8_ubo"
down_revision = "m6g_reclassify_alerts"
branch_labels = None
depends_on = None

party_kind = postgresql.ENUM("PERSON", "ENTITY", name="ubo_party_kind")
control_nature = postgresql.ENUM(
    "CAPITAL", "VOTING_RIGHTS", "EFFECTIVE_CONTROL", "LEGAL_REPRESENTATIVE",
    name="ubo_control_nature",
)


def upgrade() -> None:
    bind = op.get_bind()
    party_kind.create(bind, checkfirst=True)
    control_nature.create(bind, checkfirst=True)

    op.execute("ALTER TYPE alert_source ADD VALUE IF NOT EXISTS 'UBO'")

    op.create_table(
        "ubo_declarations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("company_ref", sa.String(), nullable=True),
        sa.Column("company_country", sa.String(64), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("risk_assessment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_screened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ubo_decl_tenant", "ubo_declarations", ["tenant_id"])
    op.create_index("ix_ubo_decl_company", "ubo_declarations", ["company_name"])

    op.create_table(
        "ubo_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("declaration_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ubo_declarations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ubo_members.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", postgresql.ENUM(name="ubo_party_kind", create_type=False),
                  nullable=False, server_default="PERSON"),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("nationality", sa.String(64), nullable=True),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("date_of_birth", sa.String(32), nullable=True),
        sa.Column("identifier", sa.String(), nullable=True),
        sa.Column("ownership_percent", sa.Numeric(6, 3), nullable=True),
        sa.Column("control_nature", postgresql.ENUM(name="ubo_control_nature", create_type=False),
                  nullable=False, server_default="CAPITAL"),
        sa.Column("is_beneficial_owner", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("screening_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("match_score", sa.Integer(), nullable=True),
        sa.Column("is_pep", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("screened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matches", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ubo_members_decl", "ubo_members", ["declaration_id"])
    op.create_index("ix_ubo_members_tenant", "ubo_members", ["tenant_id"])
    op.create_index("ix_ubo_members_parent", "ubo_members", ["parent_id"])


def downgrade() -> None:
    op.drop_table("ubo_members")
    op.drop_table("ubo_declarations")
    bind = op.get_bind()
    control_nature.drop(bind, checkfirst=True)
    party_kind.drop(bind, checkfirst=True)
    # La valeur 'UBO' de alert_source n'est pas retirée : PostgreSQL ne sait pas
    # supprimer une étiquette d'énumération.
