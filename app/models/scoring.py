"""
Module 7 — Scoring (TDR §VII).

Notation paramétrable du risque (client / transaction) par évaluation des
scénarios du Référentiel (M1). Chaque évaluation est HISTORISÉE (exigence
transverse d'historisation) sous forme de RiskAssessment.
"""
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base


class SubjectType(str, enum.Enum):
    PERSON = "PERSON"
    COMPANY = "COMPANY"
    TRANSACTION = "TRANSACTION"


class RiskClass(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskAssessment(Base):
    """Résultat historisé d'une évaluation de risque."""
    __tablename__ = "risk_assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    subject_type = Column(Enum(SubjectType, name="risk_subject_type"), nullable=False)
    subject_ref = Column(String, nullable=True, index=True)   # id du client/transaction
    subject_label = Column(String, nullable=True)             # libellé lisible

    total_score = Column(Integer, nullable=False, default=0)
    risk_class = Column(Enum(RiskClass, name="risk_class"), nullable=False, default=RiskClass.LOW)

    # Scénarios déclenchés : [{"code","name","category","severity","weight"}]
    triggered = Column(JSONB, nullable=False, default=list)
    # Contexte d'évaluation (signaux fournis / enrichis)
    context = Column(JSONB, nullable=False, default=dict)

    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    notes = Column(Text, nullable=True)
