"""baseline

Revision ID: 5cb644009daf
Revises: 8e68f1c52ab1
Create Date: 2026-01-30 18:47:49.104762

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5cb644009daf'
down_revision: Union[str, None] = '8e68f1c52ab1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
   pass

def downgrade() -> None:
   pass