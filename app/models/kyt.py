"""
Module 5 — Suivi des comportements atypiques (KYT) + sous-module Déclaration
de soupçon (TDR §VII).

- Transaction : opération ingérée depuis les systèmes exogènes (T24, SWIFT,
  ACP/ACH, RTGS) et analysée pour comportements atypiques.
- SuspiciousActivityReport (SAR) : déclaration de soupçon adressée à la Cellule
  de Conformité (réception, examen, décision).
"""
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base


class SourceSystem(str, enum.Enum):
    T24 = "T24"
    SWIFT = "SWIFT"
    ACH = "ACH"        # télé-compense ACP/ACH
    RTGS = "RTGS"
    MANUAL = "MANUAL"


class Direction(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"
    INTERNAL = "INTERNAL"


class Channel(str, enum.Enum):
    CASH = "CASH"
    WIRE = "WIRE"
    CHECK = "CHECK"
    CARD = "CARD"
    OTHER = "OTHER"


class Transaction(Base):
    __tablename__ = "kyt_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    external_ref = Column(String, nullable=True, index=True)   # référence dans le SI source
    source_system = Column(Enum(SourceSystem, name="kyt_source_system"), nullable=False)
    direction = Column(Enum(Direction, name="kyt_direction"), nullable=False, default=Direction.IN)
    channel = Column(Enum(Channel, name="kyt_channel"), nullable=False, default=Channel.WIRE)

    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")

    customer_ref = Column(String, nullable=True, index=True)     # client BCRG concerné
    counterparty_name = Column(String, nullable=True)
    counterparty_country = Column(String(64), nullable=True)     # code ISO OU nom de pays

    value_date = Column(DateTime(timezone=True), nullable=True)
    raw = Column(JSONB, nullable=False, default=dict)            # message source brut

    # résultat de l'analyse
    risk_assessment_id = Column(UUID(as_uuid=True), nullable=True)
    # décision de la Conformité sur l'opération : PENDING / BLOCKED / AUTHORIZED
    decision = Column(String(16), nullable=False, default="PENDING")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SARStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"        # transmise à la Cellule de Conformité
    UNDER_REVIEW = "UNDER_REVIEW"
    DECIDED = "DECIDED"


class SARDecision(str, enum.Enum):
    PENDING = "PENDING"
    FILED_TO_CENTIF = "FILED_TO_CENTIF"   # déclaration transmise à la CENTIF/autorité
    DISMISSED = "DISMISSED"               # classée sans suite


class SuspiciousActivityReport(Base):
    """Déclaration de soupçon (sous-module TDR)."""
    __tablename__ = "kyt_sars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    subject_ref = Column(String, nullable=True, index=True)
    subject_label = Column(String, nullable=True)
    reason = Column(String, nullable=False)
    narrative = Column(Text, nullable=True)

    status = Column(Enum(SARStatus, name="sar_status"), nullable=False, default=SARStatus.DRAFT)
    decision = Column(Enum(SARDecision, name="sar_decision"), nullable=False, default=SARDecision.PENDING)

    related_alert_id = Column(UUID(as_uuid=True), nullable=True)
    related_transaction_ids = Column(JSONB, nullable=False, default=list)

    created_by = Column(UUID(as_uuid=True), nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
