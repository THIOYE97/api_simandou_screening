"""baseline current schema

Revision ID: c2142efa601b
Revises: 41e62358e9b7
Create Date: 2026-01-19 13:27:47.193148

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2142efa601b'
down_revision: Union[str, None] = '41e62358e9b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
