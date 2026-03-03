from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_users_roles"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # uuid extension (si pas déjà)
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # enum user_role if not exists
    op.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('ANALYST','CHECKER','ADMIN');
      END IF;
    END$$;
    """)

    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Enum("ANALYST","CHECKER","ADMIN", name="user_role"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )

def downgrade():
    op.drop_table("user_roles")
    op.execute("DROP TYPE IF EXISTS user_role;")
    op.drop_table("users")
