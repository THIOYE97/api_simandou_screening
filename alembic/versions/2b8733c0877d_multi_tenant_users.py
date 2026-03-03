"""multi tenant users

Revision ID: 2b8733c0877d
Revises: 2b8eb8544e70
Create Date: 2026-01-30 18:55:22.644202

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2b8733c0877d'
down_revision: Union[str, None] = '2b8eb8544e70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
     # 1) créer tenant DEFAULT si tu n'en as pas
    op.execute("""
      INSERT INTO tenants (id, name, slug, status, created_at, updated_at)
      VALUES (gen_random_uuid(), 'DEFAULT', 'default', 'ACTIVE', now(), now())
      ON CONFLICT DO NOTHING;
    """)

    # 2) ajouter colonnes users
    op.add_column("users", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("status", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # 3) backfill tenant_id = default tenant
    op.execute("""
      UPDATE users
      SET tenant_id = (SELECT id FROM tenants WHERE slug='default' LIMIT 1)
      WHERE tenant_id IS NULL;
    """)

    # 4) backfill status + updated_at
    op.execute("UPDATE users SET status = COALESCE(status, 'ACTIVE') WHERE status IS NULL;")
    op.execute("UPDATE users SET updated_at = COALESCE(updated_at, created_at, now()) WHERE updated_at IS NULL;")

    # 5) constraints
    op.execute("ALTER TABLE users ALTER COLUMN tenant_id SET NOT NULL;")
    op.execute("ALTER TABLE users ALTER COLUMN status SET DEFAULT 'ACTIVE';")
    op.execute("ALTER TABLE users ALTER COLUMN status SET NOT NULL;")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at SET DEFAULT now();")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at SET NOT NULL;")

    op.execute("""
      DO $$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_status_check') THEN
          ALTER TABLE users
          ADD CONSTRAINT users_status_check
          CHECK (status IN ('ACTIVE','INVITED','DISABLED'));
        END IF;
      END $$;
    """)

    # FK
    op.create_foreign_key(
        "fk_users_tenant_id",
        "users",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # email unique global
    # (si email pas déjà unique)
    op.create_index("ux_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_index("idx_users_tenant_id", "users", ["tenant_id"], unique=False)



def downgrade() -> None:
    op.drop_index("idx_users_tenant_id", table_name="users")
    op.drop_index("ux_users_email_lower", table_name="users")
    op.drop_constraint("fk_users_tenant_id", "users", type_="foreignkey")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "status")
    op.drop_column("users", "tenant_id")
