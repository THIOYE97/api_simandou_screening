"""merge baseline with cases kyb docs

Revision ID: 41e62358e9b7
Revises: 005_documents, 89b9122cb96e
Create Date: 2026-01-19 12:52:34.678703

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41e62358e9b7'
down_revision: Union[str, None] = ('005_documents', '89b9122cb96e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
