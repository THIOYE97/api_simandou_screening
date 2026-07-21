"""m9: pièces justificatives des déclarations de bénéficiaires effectifs.

Revision ID: m9_ubo_documents
Revises: m8_ubo
Create Date: 2026-07-21

Une déclaration sans pièce à l'appui est invérifiable : en inspection, c'est le
document (statuts, registre des actionnaires) qui fait foi, pas la saisie.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "m9_ubo_documents"
down_revision = "m8_ubo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ubo_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("declaration_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ubo_declarations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("doc_type", sa.String(48), nullable=False, server_default="AUTRE"),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("storage_backend", sa.String(16), nullable=False, server_default="LOCAL"),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_ubo_docs_decl", "ubo_documents", ["declaration_id"])
    op.create_index("ix_ubo_docs_tenant", "ubo_documents", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("ubo_documents")
