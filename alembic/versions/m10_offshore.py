"""m10: base séparée des fuites offshore (ICIJ).

Revision ID: m10_offshore
Revises: m9_ubo_documents
Create Date: 2026-07-21

Base tenue à l'ÉCART de l'index de filtrage : 1,6 million d'enregistrements
contre 55 000 pour les sanctions, une nature différente (piste d'enquête et non
motif de blocage) et une licence à réciprocité qu'il ne faut pas propager.

Index trigramme sur le nom normalisé : la recherche se fait par ressemblance,
les graphies variant fortement dans ces corpus.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "m10_offshore"
down_revision = "m9_ubo_documents"
branch_labels = None
depends_on = None

offshore_kind = postgresql.ENUM("ENTITY", "OFFICER", "INTERMEDIARY", name="offshore_kind")


def upgrade() -> None:
    bind = op.get_bind()
    offshore_kind.create(bind, checkfirst=True)

    op.create_table(
        "offshore_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(32), nullable=False),
        sa.Column("kind", postgresql.ENUM(name="offshore_kind", create_type=False), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_normalized", sa.String(), nullable=False),
        sa.Column("countries", sa.String(), nullable=True),
        sa.Column("country_codes", sa.String(128), nullable=True),
        sa.Column("jurisdiction", sa.String(128), nullable=True),
        sa.Column("investigation", sa.String(128), nullable=True),
        sa.Column("incorporation_date", sa.String(32), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # Unicité (node_id, kind) : c'est elle qui porte l'idempotence de l'import.
    # Sans elle, il faudrait charger 1,6 million d'identifiants en mémoire à
    # chaque tranche pour savoir ce qui existe déjà.
    op.create_index("ux_offshore_node_kind", "offshore_records", ["node_id", "kind"], unique=True)
    op.create_index("ix_offshore_kind", "offshore_records", ["kind"])
    # Recherche par ressemblance : les graphies varient beaucoup dans ces corpus.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX ix_offshore_norm_trgm ON offshore_records "
               "USING gin (name_normalized gin_trgm_ops)")


def downgrade() -> None:
    op.drop_table("offshore_records")
    offshore_kind.drop(op.get_bind(), checkfirst=True)
