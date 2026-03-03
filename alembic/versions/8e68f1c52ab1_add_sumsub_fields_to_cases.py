"""add sumsub fields to cases

Revision ID: 8e68f1c52ab1
Revises: ca2bdb0d51ce
Create Date: 2026-01-24 11:12:31.835924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e68f1c52ab1'
down_revision: Union[str, None] = 'ca2bdb0d51ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
