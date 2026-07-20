"""m6f: libellés explicites des listes de surveillance (catégorie réelle).

Revision ID: m6f_source_names
Revises: m6e_case_type_kys
Create Date: 2026-07-19

Les listes s'affichaient avec des noms techniques ou anglais (« SGG PEP Lists »)
qui n'indiquaient pas leur nature. On préfixe chaque source par sa CATÉGORIE
réelle — « Sanctions » ou « PPE Guinée » — pour que la Conformité sache
immédiatement contre quoi une personne est filtrée.

Ciblage par source_code (et non par id) pour rester valable sur tout
environnement. Idempotent : rejouable sans effet de bord.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

# revision identifiers
revision = "m6f_source_names"
down_revision = "m6e_case_type_kys"
branch_labels = None
depends_on = None

_NAMES = {
    "UN":     "Sanctions — Nations Unies (liste consolidée)",
    "OFAC":   "Sanctions — OFAC (Trésor américain)",
    "EU":     "Sanctions — Union Européenne",
    "UK":     "Sanctions — Royaume-Uni",
    "SGG":    "PPE Guinée — Répertoire SGG",
    "SGG_GN": "PPE Guinée — Journal Officiel (SGG)",
    "GN_GOV": "PPE Guinée — Membres du Gouvernement (Ve République)",
}


def upgrade() -> None:
    conn = op.get_bind()
    for code, name in _NAMES.items():
        conn.execute(
            text("UPDATE sources SET source_name = :n WHERE source_code = :c"),
            {"n": name, "c": code},
        )


def downgrade() -> None:
    # Les anciens libellés n'ont pas de valeur métier : pas de restauration.
    pass
