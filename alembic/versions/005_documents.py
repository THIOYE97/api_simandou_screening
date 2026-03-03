from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_documents"
down_revision = "004_kyc_kyb"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'storage_backend') THEN
        CREATE TYPE storage_backend AS ENUM ('LOCAL','S3');
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ocr_status') THEN
        CREATE TYPE ocr_status AS ENUM ('PENDING','DONE','LOW_CONFIDENCE','FAILED');
      END IF;
    END$$;
    """)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),

        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("storage_backend", sa.Enum("LOCAL","S3", name="storage_backend"), nullable=False, server_default=sa.text("'LOCAL'::storage_backend")),
        sa.Column("object_key", sa.Text(), nullable=False),

        sa.Column("original_filename", sa.Text()),
        sa.Column("mime_type", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("sha256", sa.Text()),

        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("uploaded_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),

        sa.Column("ocr_status", sa.Enum("PENDING","DONE","LOW_CONFIDENCE","FAILED", name="ocr_status"),
                  nullable=False, server_default=sa.text("'PENDING'::ocr_status")),
        sa.Column("ocr_confidence", sa.Numeric(4,3)),
        sa.Column("extracted_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_index("idx_documents_case", "documents", ["case_id", "uploaded_at"])
    op.create_unique_constraint("uq_documents_object", "documents", ["storage_backend", "object_key"])

def downgrade():
    op.drop_constraint("uq_documents_object", "documents", type_="unique")
    op.drop_index("idx_documents_case", table_name="documents")
    op.drop_table("documents")
    op.execute("DROP TYPE IF EXISTS ocr_status;")
    op.execute("DROP TYPE IF EXISTS storage_backend;")
