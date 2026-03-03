"""add sumsub fields to cases

Revision ID: ca2bdb0d51ce
Revises: c2142efa601b
Create Date: 2026-01-20 14:17:02.065495

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca2bdb0d51ce'
down_revision: Union[str, None] = 'c2142efa601b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.add_column("cases", sa.Column("sumsub_review_status", sa.Text(), nullable=True))
    op.add_column("cases", sa.Column("sumsub_review_answer", sa.Text(), nullable=True))
    op.add_column("cases", sa.Column("sumsub_last_event_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("sumsub_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # sumsub_applicant_id exists already in your schema, so only add if NOT present.
    # If you're not sure, comment this out and check the DB schema.
    # op.add_column("cases", sa.Column("sumsub_applicant_id", sa.Text(), nullable=True))

    # index if not already created
    # If sumsub_applicant_id column already had index=True, it may already exist.
    # Creating again can fail, so use a stable name and "if not exists" pattern via raw SQL:
    op.execute("CREATE INDEX IF NOT EXISTS ix_cases_sumsub_applicant_id ON cases (sumsub_applicant_id)")


def downgrade():
    op.drop_column("cases", "sumsub_snapshot")
    op.drop_column("cases", "sumsub_last_event_at")
    op.drop_column("cases", "sumsub_review_answer")
    op.drop_column("cases", "sumsub_review_status")
    op.execute("DROP INDEX IF EXISTS ix_cases_sumsub_applicant_id")