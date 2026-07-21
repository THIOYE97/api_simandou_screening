"""m12 : cache partagé des recherches de presse.

La recherche de presse devient asynchrone : l'écran la déclenche, puis sonde
jusqu'au résultat. Le cache DOIT être en base, pas en mémoire — la production
tourne avec deux workers gunicorn et rien ne garantit que le sondage atteigne
celui qui a lancé la recherche. Un cache en mémoire ferait tourner l'écran
indéfiniment une fois sur deux.

Il sert aussi de mémoire durable : la source refuse environ deux requêtes sur
trois, et une société déjà interrogée ne doit plus jamais dépendre d'elle
pendant la durée de validité.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "m12_press_cache"
down_revision = "m11_adverse_media_trgm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "press_search_cache",
        # Le nom normalisé est la clé : « Glencore » et « GLENCORE » sont une
        # seule et même recherche, inutile de solliciter deux fois la source.
        sa.Column("name_normalized", sa.String(300), primary_key=True),
        sa.Column("display_name", sa.String(300), nullable=False),
        # PENDING (recherche en cours) | DONE | ERROR
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("articles", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # Le balayage des entrées périmées se fait par date.
    op.create_index("ix_press_cache_updated", "press_search_cache", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_press_cache_updated", table_name="press_search_cache")
    op.drop_table("press_search_cache")
