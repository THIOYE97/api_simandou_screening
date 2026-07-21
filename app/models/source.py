"""
Sources de listes (sanctions, PPE, listes propres à la BCRG).

La table existait en production sans modèle ORM correspondant : elle était
donc absente du registre, et donc absente des bases de test construites à
partir des modèles. Tout test touchant au chargement ou au rafraîchissement
des listes échouait de ce fait.
"""
from sqlalchemy import Boolean, Column, Enum, SmallInteger, Text

from app.models.base import Base

# Aligné sur le type PostgreSQL `source_type` déjà en place.
SourceType = Enum(
    "SANCTIONS", "PEP_RULES", "WATCHLIST", "INTERNAL",
    name="source_type",
    create_type=False,
    validate_strings=False,
)


class Source(Base):
    __tablename__ = "sources"

    id = Column(SmallInteger, primary_key=True, autoincrement=True)
    source_code = Column(Text, nullable=False, unique=True)
    source_name = Column(Text, nullable=False)
    source_type = Column(SourceType, nullable=False)
    country = Column(Text, nullable=True)
    # Rythme de mise à jour attendu (MANUAL, DAILY…). Le Cron Job quotidien
    # rafraîchit toutes les sources qu'un serveur peut télécharger seul.
    refresh_policy = Column(Text, nullable=False, default="MANUAL")
    is_active = Column(Boolean, nullable=False, default=True)
