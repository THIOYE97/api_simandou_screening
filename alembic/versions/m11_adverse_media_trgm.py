"""m11 : index trigramme sur la base adverse media.

Le rapprochement des médias défavorables devient systématique sur les
personnes morales. Sans index, chaque vérification chargerait toute la base
en mémoire pour la parcourir ligne à ligne en Python — tenable sur quelques
enregistrements de démonstration, plus du tout dès que la Conformité alimente
réellement la base.

Seul l'opérateur « % » de pg_trgm exploite cet index ; écrire
« similarity(...) > seuil » dans le WHERE le contournerait silencieusement.
"""
from __future__ import annotations

from alembic import op

revision = "m11_adverse_media_trgm"
down_revision = "m10_offshore"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_adverse_media_norm_trgm "
        "ON adverse_media_records USING gin (normalized_name gin_trgm_ops)"
    )
    # Le filtrage ne retient que les signalements actifs : les écarter par
    # l'index évite de scorer des enregistrements désactivés.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_adverse_media_active "
        "ON adverse_media_records (active)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_adverse_media_active")
    op.execute("DROP INDEX IF EXISTS ix_adverse_media_norm_trgm")
