"""m13 : liens entre acteurs des fuites offshore (ICIJ).

Sans ces arêtes, la base offshore ne sait que rapprocher des noms. Avec elles,
une vérification de personne morale remonte les détenteurs potentiels, et une
vérification de personne physique les sociétés rattachées.

Seuls les liens « officer_of » sont chargés : ce sont ceux qui portent une
détention ou une fonction. Les adresses partagées et les homonymies
(« registered_address », « same_name_as ») ne disent rien d'une détention et
représenteraient un million de lignes de bruit.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m13_offshore_relations"
down_revision = "m12_press_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offshore_relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id_start", sa.String(32), nullable=False),
        sa.Column("node_id_end", sa.String(32), nullable=False),
        sa.Column("rel_type", sa.String(32), nullable=False),
        sa.Column("role_raw", sa.String(160), nullable=True),
        # BENEFICIAL_OWNER | SHAREHOLDER | MANAGEMENT | OTHER
        sa.Column("role_class", sa.String(24), nullable=False),
        sa.Column("source", sa.String(128), nullable=True),
    )
    # Les deux sens de lecture sont nécessaires : d'une société vers ses
    # détenteurs, et d'une personne vers ses sociétés.
    op.create_index("ix_offshore_rel_start", "offshore_relations", ["node_id_start"])
    op.create_index("ix_offshore_rel_end", "offshore_relations", ["node_id_end"])
    # Porte l'idempotence : sur 1,7 million d'arêtes, tenir la liste des
    # existantes en mémoire coûterait des centaines de Mo.
    op.create_index("ux_offshore_rel", "offshore_relations",
                    ["node_id_start", "node_id_end", "rel_type", "role_raw"],
                    unique=True)


def downgrade() -> None:
    op.drop_table("offshore_relations")
