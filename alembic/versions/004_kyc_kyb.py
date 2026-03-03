from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_kyc_kyb"
down_revision = "003_case_entities"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "persons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, unique=True),

        sa.Column("last_name", sa.Text()),
        sa.Column("first_names", sa.Text()),
        sa.Column("date_of_birth", sa.Date()),
        sa.Column("place_of_birth", sa.Text()),
        sa.Column("nationality", sa.Text()),

        sa.Column("address", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("email", sa.Text()),

        sa.Column("document_type", sa.Text()),
        sa.Column("document_number", sa.Text()),
        sa.Column("document_expiry", sa.Date()),
        sa.Column("document_issue_country", sa.Text()),

        sa.Column("ppe_status", sa.Boolean()),
        sa.Column("client_code", sa.Text()),

        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, unique=True),

        sa.Column("legal_name", sa.Text()),
        sa.Column("legal_form", sa.Text()),
        sa.Column("rccm", sa.Text()),
        sa.Column("nif", sa.Text()),
        sa.Column("client_code", sa.Text()),

        sa.Column("address_full", sa.Text()),
        sa.Column("city", sa.Text()),
        sa.Column("commune", sa.Text()),

        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("idx_companies_rccm", "companies", ["rccm"])
    op.create_index("idx_companies_nif", "companies", ["nif"])

    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'company_role_type') THEN
        CREATE TYPE company_role_type AS ENUM ('DIRECTOR','UBO');
      END IF;
    END$$;
    """)

    op.create_table(
        "company_people",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_type", sa.Enum("DIRECTOR","UBO", name="company_role_type"), nullable=False),
        sa.Column("ownership_pct", sa.Numeric(5,2)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("company_id", "person_id", "role_type", name="uq_company_person_role"),
        sa.CheckConstraint("role_type <> 'UBO' OR (ownership_pct IS NOT NULL AND ownership_pct >= 25.0)", name="chk_ubo_pct"),
    )

def downgrade():
    op.drop_table("company_people")
    op.execute("DROP TYPE IF EXISTS company_role_type;")
    op.drop_index("idx_companies_nif", table_name="companies")
    op.drop_index("idx_companies_rccm", table_name="companies")
    op.drop_table("companies")
    op.drop_table("persons")
