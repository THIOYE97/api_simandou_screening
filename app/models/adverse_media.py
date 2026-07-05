"""
Adverse media (TDR §VI — « vérifications en lien avec les adverse media »).

Base consultable d'articles/signalements négatifs rattachés à des entités, avec
catégorie de risque, source et date. Le screening rapproche un nom candidat de
cette base via le moteur de matching flou.
"""
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class AdverseMediaCategory(str, enum.Enum):
    FRAUD = "FRAUD"
    CORRUPTION = "CORRUPTION"
    MONEY_LAUNDERING = "MONEY_LAUNDERING"
    TERRORISM = "TERRORISM"
    TRAFFICKING = "TRAFFICKING"
    SANCTIONS_EVASION = "SANCTIONS_EVASION"
    ORGANIZED_CRIME = "ORGANIZED_CRIME"
    OTHER = "OTHER"


class AdverseMediaRecord(Base):
    __tablename__ = "adverse_media_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, index=True)
    category = Column(Enum(AdverseMediaCategory, name="adverse_media_category"), nullable=False)
    source = Column(String, nullable=True)          # média / source
    url = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
