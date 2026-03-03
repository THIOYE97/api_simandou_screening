from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003_case_entities"
down_revision = "002_cases"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'case_entity_role') THEN
        CREATE TYPE case_entity_role AS ENUM ('PRIMARY_PERSON','PRIMARY_COMPANY','DIRECTOR','UBO');
      END IF;
    END$$;
    """)

    op.create_table(
        "case_entities",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Enum("PRIMARY_PERSON","PRIMARY_COMPANY","DIRECTOR","UBO", name="case_entity_role"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("case_id", "entity_id", "role"),
    )

    op.create_index("idx_case_entities_case", "case_entities", ["case_id"])
    op.create_index("idx_case_entities_entity", "case_entities", ["entity_id"])

def downgrade():
    op.drop_index("idx_case_entities_entity", table_name="case_entities")
    op.drop_index("idx_case_entities_case", table_name="case_entities")
    op.drop_table("case_entities")
    op.execute("DROP TYPE IF EXISTS case_entity_role;")
