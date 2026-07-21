"""
Sources de listes (sanctions, PPE, listes propres à la BCRG).

La table existait en production sans modèle ORM correspondant : elle était
donc absente du registre, et donc absente des bases de test construites à
partir des modèles. Tout test touchant au chargement ou au rafraîchissement
des listes échouait de ce fait.
"""
from sqlalchemy import Boolean, Column, Enum, SmallInteger, Text

from app.models.base import Base

# Valeurs EXACTES du type PostgreSQL `source_type`. Une première rédaction
# citait « WATCHLIST » et « INTERNAL », qui n'existent pas — et omettait
# « OFFICIAL_NOTICE » et « OTHER », qui sont précisément ceux dont une liste
# propre à la BCRG a besoin.
SourceType = Enum(
    "SANCTIONS", "OFFICIAL_NOTICE", "PEP_RULES", "OTHER",
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
