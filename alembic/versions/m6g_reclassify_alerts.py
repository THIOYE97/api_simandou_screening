"""m6g: reclasse les alertes historiques par origine métier.

Revision ID: m6g_reclassify_alerts
Revises: m6f_source_names
Create Date: 2026-07-20

Avant la qualification des origines, TOUTES les alertes étaient écrites en
« SCORING », donc indistinguables entre une vérification de client et une
opération atypique. On reclasse l'existant :

  - une alerte dont l'évaluation est rattachée à une transaction  -> KYT ;
  - toutes les autres                                            -> SCREENING.

Idempotent : ne touche que les lignes restées en SCORING.
"""
from __future__ import annotations

from alembic import op

# revision identifiers
revision = "m6g_reclassify_alerts"
down_revision = "m6f_source_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Alertes liées à une opération.
    op.execute("""
        UPDATE alerts a
           SET source = 'KYT'::alert_source
         WHERE a.source = 'SCORING'::alert_source
           AND a.risk_assessment_id IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM kyt_transactions t
                WHERE t.risk_assessment_id = a.risk_assessment_id
           )
    """)
    # 2) Le reste provient d'une vérification de personne/fournisseur.
    op.execute("""
        UPDATE alerts
           SET source = 'SCREENING'::alert_source
         WHERE source = 'SCORING'::alert_source
    """)


def downgrade() -> None:
    # L'origine d'avant était uniformément SCORING : on peut la rétablir.
    op.execute("""
        UPDATE alerts
           SET source = 'SCORING'::alert_source
         WHERE source IN ('KYT'::alert_source, 'SCREENING'::alert_source)
    """)
