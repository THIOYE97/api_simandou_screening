"""
Liens entre acteurs des fuites offshore (ICIJ).

Sans ces arêtes, la base offshore ne permet que de rapprocher des noms. Avec
elles, on remonte d'une société à ceux qui la détiennent, et d'une personne
aux sociétés qu'elle contrôle — ce qui intéresse la LBC/FT.

Le rôle brut de l'ICIJ compte 716 libellés distincts. Il est conservé tel quel
pour la traçabilité, et classé dans quelques catégories exploitables : un
« ultimate beneficial owner » et un « auditor of » ne se lisent pas de la même
façon dans un dossier.

Réserve constante : ces données s'arrêtent en 2020 et ne sont pas un registre
de bénéficiaires effectifs. Elles désignent des détenteurs POTENTIELS, à
confirmer — jamais une détention établie.
"""
from sqlalchemy import Column, Index, Integer, String

from app.models.base import Base


class OffshoreRelation(Base):
    __tablename__ = "offshore_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Identifiants ICIJ, mis en correspondance avec offshore_records.node_id.
    node_id_start = Column(String(32), nullable=False)
    node_id_end = Column(String(32), nullable=False)
    rel_type = Column(String(32), nullable=False)
    # Libellé d'origine (« ultimate beneficial owner », « director of »…).
    role_raw = Column(String(160), nullable=True)
    # BENEFICIAL_OWNER | SHAREHOLDER | MANAGEMENT | OTHER
    role_class = Column(String(24), nullable=False)
    source = Column(String(128), nullable=True)

    __table_args__ = (
        # Les deux sens de lecture sont nécessaires : d'une société vers ses
        # détenteurs, et d'une personne vers ses sociétés.
        Index("ix_offshore_rel_start", "node_id_start"),
        Index("ix_offshore_rel_end", "node_id_end"),
        # Porte l'idempotence de l'import : une arête déjà chargée est ignorée.
        Index("ux_offshore_rel", "node_id_start", "node_id_end", "rel_type",
              "role_raw", unique=True),
    )
