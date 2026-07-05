"""
Module 6 — Alerte (TDR §VII), 3 sous-modules :
- Paramétrage  : AlertRule (règles déclenchantes paramétrables) ;
- Administration : cycle de vie de l'Alert (affectation, statut, résolution) ;
- Détection des occurrences : génération d'Alert à partir du scoring/screening/KYT.
"""
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base


class AlertSource(str, enum.Enum):
    SCREENING = "SCREENING"
    SCORING = "SCORING"
    KYT = "KYT"
    MANUAL = "MANUAL"


class AlertSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    ESCALATED = "ESCALATED"
    CLOSED_TRUE_POSITIVE = "CLOSED_TRUE_POSITIVE"
    CLOSED_FALSE_POSITIVE = "CLOSED_FALSE_POSITIVE"


class AlertRule(Base):
    """Règle paramétrable de génération d'alerte (sous-module Paramétrage)."""
    __tablename__ = "alert_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    source = Column(Enum(AlertSource, name="alert_source"), nullable=False, default=AlertSource.SCORING)
    severity = Column(Enum(AlertSeverity, name="alert_severity"), nullable=False, default=AlertSeverity.MEDIUM)

    # Condition paramétrable évaluée contre le contexte d'une occurrence, ex :
    #   {"field": "risk_class", "op": "in", "value": ["HIGH", "CRITICAL"]}
    #   {"field": "max_severity", "op": "==", "value": "CRITICAL"}
    condition = Column(JSONB, nullable=False, default=dict)
    auto_escalate = Column(Boolean, nullable=False, default=False)  # crée l'alerte directement en ESCALATED

    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Alert(Base):
    """Occurrence d'alerte + cycle de vie (sous-module Administration)."""
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    source = Column(Enum(AlertSource, name="alert_source"), nullable=False)
    severity = Column(Enum(AlertSeverity, name="alert_severity"), nullable=False, default=AlertSeverity.MEDIUM)
    status = Column(Enum(AlertStatus, name="alert_status"), nullable=False, default=AlertStatus.OPEN)

    title = Column(String, nullable=False)
    rule_code = Column(String, nullable=True, index=True)
    subject_ref = Column(String, nullable=True, index=True)
    subject_label = Column(String, nullable=True)
    risk_assessment_id = Column(UUID(as_uuid=True), nullable=True)

    detail = Column(JSONB, nullable=False, default=dict)

    assigned_to = Column(UUID(as_uuid=True), nullable=True)
    resolution = Column(Text, nullable=True)
    resolved_by = Column(UUID(as_uuid=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
