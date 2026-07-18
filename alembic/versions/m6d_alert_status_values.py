"""m6d: aligne l'enum alert_status avec les statuts applicatifs.

Revision ID: m6d_alert_status_values
Revises: m6b_compliance_audit
Create Date: 2026-07-18

Contexte :
  L'enum public.alert_status pré-existait dans le baseline avec 3 valeurs
  (OPEN, FALSE_POSITIVE, CONFIRMED). La migration m6_alerting a créé la table
  `alerts` en réutilisant ce type via checkfirst=True — donc SANS ajouter les
  valeurs attendues par le workflow Conformité (IN_REVIEW, ESCALATED,
  CLOSED_TRUE_POSITIVE, CLOSED_FALSE_POSITIVE). Résultat : écrire l'un de ces
  statuts déclenche `invalid input value for enum alert_status`.

Correctif :
  ALTER TYPE ... ADD VALUE IF NOT EXISTS (idempotent). Les anciennes valeurs
  FALSE_POSITIVE / CONFIRMED restent (inoffensives, non utilisées par le code).

NB : ADD VALUE est autorisé dans une transaction sur PostgreSQL >= 12 tant que
     la nouvelle valeur n'est pas utilisée dans la même transaction (c'est le
     cas ici : on ne fait qu'ajouter).
"""
from __future__ import annotations

from alembic import op

# revision identifiers
revision = "m6d_alert_status_values"
down_revision = "m6b_compliance_audit"
branch_labels = None
depends_on = None

_MISSING = ["IN_REVIEW", "ESCALATED", "CLOSED_TRUE_POSITIVE", "CLOSED_FALSE_POSITIVE"]


def upgrade() -> None:
    for value in _MISSING:
        op.execute(f"ALTER TYPE public.alert_status ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL ne permet pas de retirer une valeur d'enum : no-op.
    pass
