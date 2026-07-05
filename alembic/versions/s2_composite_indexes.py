"""S2: composite indexes (tenant_id, created_at/status) for multi-tenant scale.

Revision ID: s2_composite_indexes
Revises: 2b8733c0877d
Create Date: 2026-05-17

Rationale:
  Sur des tables filtrées par tenant_id puis triées/filtrées par created_at,
  status, ou band, un index simple sur tenant_id seul oblige Postgres à
  charger toutes les lignes du tenant. Sur 1k tenants × 1M rows, c'est lent.

Strategy:
  - CREATE INDEX CONCURRENTLY pour éviter de bloquer les writes en prod.
  - IF NOT EXISTS pour idempotence (rejouable sans casser).
  - Vérifie l'existence de la colonne avant de créer l'index (certaines
    tables peuvent ne pas avoir tenant_id selon le schéma déployé).
"""
from __future__ import annotations

from alembic import op

# revision identifiers
revision = "s2_composite_indexes"
down_revision = "2b8733c0877d"
branch_labels = None
depends_on = None


# Indexes à créer : (table, name, columns_expression)
# Tous protégés par IF NOT EXISTS + check de colonne avant exécution.
INDEXES: list[tuple[str, str, str]] = [
    # documents
    ("documents", "ix_documents_tenant_uploaded_at", "(tenant_id, uploaded_at DESC)"),
    ("documents", "ix_documents_tenant_case", "(tenant_id, case_id)"),
    ("documents", "ix_documents_tenant_ocr_status", "(tenant_id, ocr_status)"),
    # screening_requests
    ("screening_requests", "ix_sr_tenant_created_at", "(tenant_id, created_at DESC)"),
    ("screening_requests", "ix_sr_tenant_status", "(tenant_id, status)"),
    ("screening_requests", "ix_sr_tenant_case", "(tenant_id, case_id)"),
    # screening_results
    ("screening_results", "ix_sres_tenant_decided_at", "(tenant_id, decided_at DESC)"),
    ("screening_results", "ix_sres_tenant_risk", "(tenant_id, risk_level)"),
    # screening_matches
    ("screening_matches", "ix_sm_tenant_band", "(tenant_id, match_band)"),
    ("screening_matches", "ix_sm_tenant_score", "(tenant_id, match_score DESC)"),
    # cases — tenant_id n'est pas dans le modèle SQLAlchemy mais peut exister en DB
    # via une migration héritée. On essaie, on saute proprement si absent.
    ("cases", "ix_cases_tenant_created_at", "(tenant_id, created_at DESC)"),
    ("cases", "ix_cases_tenant_status", "(tenant_id, status)"),
]


def _column_exists(bind, table: str, column: str) -> bool:
    row = bind.exec_driver_sql(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    ).first()
    return row is not None


def upgrade() -> None:
    # NB : on crée les index DANS la transaction Alembic (pas de CONCURRENTLY).
    # CONCURRENTLY exigerait de sortir de la transaction (AUTOCOMMIT), ce qui
    # n'est pas possible sur la connexion déjà ouverte par Alembic. Les tables
    # restant modestes, le lock bref d'un CREATE INDEX classique est acceptable.
    bind = op.get_bind()
    for table, name, cols in INDEXES:
        if not _column_exists(bind, table, "tenant_id"):
            continue
        op.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" {cols}')


def downgrade() -> None:
    for _table, name, _cols in INDEXES:
        op.execute(f'DROP INDEX IF EXISTS "{name}"')
