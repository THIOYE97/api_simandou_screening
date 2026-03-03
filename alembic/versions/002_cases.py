from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_cases"
down_revision = "001_users_roles"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'case_type') THEN
        CREATE TYPE case_type AS ENUM ('KYC','KYB');
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'case_status') THEN
        CREATE TYPE case_status AS ENUM ('DRAFT','PENDING_REVIEW','ACTION_REQUIRED','APPROVED','REJECTED');
      END IF;
    END$$;
    """)

    # risk_level enum already exists in your DB (entities.risk_level). We reuse it.
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("case_type", sa.Enum("KYC","KYB", name="case_type"), nullable=False),
        sa.Column("status", sa.Enum("DRAFT","PENDING_REVIEW","ACTION_REQUIRED","APPROVED","REJECTED", name="case_status"),
                  nullable=False, server_default=sa.text("'DRAFT'::case_status")),
        sa.Column("risk_level", sa.Enum(name="risk_level"), nullable=False, server_default=sa.text("'LOW'::risk_level")),

        sa.Column("urgent_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("urgent_reason", sa.Text(), nullable=True),

        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("assigned_checker", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),

        sa.Column("last_screening_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

def downgrade():
    op.drop_table("cases")
    op.execute("DROP TYPE IF EXISTS case_status;")
    op.execute("DROP TYPE IF EXISTS case_type;")
