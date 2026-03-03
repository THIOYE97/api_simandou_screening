"""add tenants fields

Revision ID: 2b8eb8544e70
Revises: 5cb644009daf
Create Date: 2026-01-30 18:48:31.774462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b8eb8544e70'
down_revision: Union[str, None] = '5cb644009daf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("tenants", sa.Column("status", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("active_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("active_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # backfill
    op.execute("UPDATE tenants SET status = COALESCE(status, 'ACTIVE') WHERE status IS NULL;")
    op.execute("UPDATE tenants SET updated_at = COALESCE(updated_at, created_at, now()) WHERE updated_at IS NULL;")

    # defaults + not null
    op.execute("ALTER TABLE tenants ALTER COLUMN status SET DEFAULT 'ACTIVE';")
    op.execute("ALTER TABLE tenants ALTER COLUMN status SET NOT NULL;")
    op.execute("ALTER TABLE tenants ALTER COLUMN updated_at SET DEFAULT now();")
    op.execute("ALTER TABLE tenants ALTER COLUMN updated_at SET NOT NULL;")

    # check constraint
    op.execute("""
      DO $$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tenants_status_check') THEN
          ALTER TABLE tenants
          ADD CONSTRAINT tenants_status_check
          CHECK (status IN ('ACTIVE','SUSPENDED','DISABLED','EXPIRED'));
        END IF;
      END $$;
    """)

    op.create_index("idx_tenants_status", "tenants", ["status"], unique=False)
    op.create_index("idx_tenants_active_until", "tenants", ["active_until"], unique=False)

    # updated_at trigger
    op.execute("""
      CREATE OR REPLACE FUNCTION set_updated_at()
      RETURNS trigger AS $$
      BEGIN
        NEW.updated_at = now();
        RETURN NEW;
      END;
      $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_tenants_updated_at ON tenants;")
    op.execute("""
      CREATE TRIGGER trg_tenants_updated_at
      BEFORE UPDATE ON tenants
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
    """)

def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_tenants_updated_at ON tenants;")
    # on ne drop pas function si partagée
    op.drop_index("idx_tenants_active_until", table_name="tenants")
    op.drop_index("idx_tenants_status", table_name="tenants")
    op.drop_column("tenants", "updated_at")
    op.drop_column("tenants", "active_until")
    op.drop_column("tenants", "active_from")
    op.drop_column("tenants", "status")