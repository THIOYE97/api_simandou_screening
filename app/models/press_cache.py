"""
Cache partagé des recherches de presse (médias défavorables).

En base et non en mémoire : la production tourne avec deux workers gunicorn et
rien ne garantit que le sondage de l'écran atteigne celui qui a lancé la
recherche. Un cache en mémoire ferait tourner l'écran indéfiniment une fois
sur deux.

Il sert aussi de mémoire durable : la source publique refuse environ deux
requêtes sur trois, et une société déjà interrogée ne doit plus dépendre
d'elle pendant la durée de validité.
"""
from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.models.base import Base


class PressSearchCache(Base):
    __tablename__ = "press_search_cache"

    # Le nom normalisé est la clé : « Glencore » et « GLENCORE » sont une seule
    # et même recherche.
    name_normalized = Column(String(300), primary_key=True)
    display_name = Column(String(300), nullable=False)
    # PENDING (recherche en cours) | DONE | ERROR
    status = Column(String(16), nullable=False)
    articles = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
