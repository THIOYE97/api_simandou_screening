"""m6e: renomme le type de dossier KYB -> KYS (Know Your Supplier).

Revision ID: m6e_case_type_kys
Revises: m6d_alert_status_values
Create Date: 2026-07-19

Contexte métier :
  À la Banque Centrale, on parle de « fournisseur » (supplier) et non de
  « business ». Le type de dossier devient donc KYC / KYS.

Technique :
  `case_type` est un ENUM PostgreSQL ('KYC','KYB') porté par cases.case_type,
  avec des lignes existantes en 'KYB'. PostgreSQL ne sait pas supprimer une
  valeur d'ENUM, et interdit d'utiliser une valeur fraîchement ajoutée dans la
  même transaction. On recrée donc le type et on convertit la colonne en une
  seule passe (USING), ce qui est transactionnel et sans perte.
"""
from __future__ import annotations

from alembic import op

# revision identifiers
revision = "m6e_case_type_kys"
down_revision = "m6d_alert_status_values"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE case_type_new AS ENUM ('KYC', 'KYS')")
    op.execute("""
        ALTER TABLE cases
            ALTER COLUMN case_type TYPE case_type_new
            USING (
                CASE WHEN case_type::text = 'KYB' THEN 'KYS' ELSE case_type::text END
            )::case_type_new
    """)
    op.execute("DROP TYPE case_type")
    op.execute("ALTER TYPE case_type_new RENAME TO case_type")


def downgrade() -> None:
    op.execute("CREATE TYPE case_type_old AS ENUM ('KYC', 'KYB')")
    op.execute("""
        ALTER TABLE cases
            ALTER COLUMN case_type TYPE case_type_old
            USING (
                CASE WHEN case_type::text = 'KYS' THEN 'KYB' ELSE case_type::text END
            )::case_type_old
    """)
    op.execute("DROP TYPE case_type")
    op.execute("ALTER TYPE case_type_old RENAME TO case_type")
