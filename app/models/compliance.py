"""
Piste d'audit des décisions de Conformité.

Chaque décision prise sur une alerte (prise en charge, escalade, confirmation,
levée) est journalisée et rattachée au SUJET (une vérification de personne ou
une opération), pour être consultable et auditable depuis le détail de la
vérification correspondante.
"""
import uuid

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class ComplianceEvent(Base):
    __tablename__ = "compliance_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    alert_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # rattachement au sujet auditable
    subject_kind = Column(String(16), nullable=False)   # SCREENING / TRANSACTION / PERSON
    subject_id = Column(String, nullable=True, index=True)  # request_id ou id d'opération
    subject_label = Column(String, nullable=True)

    action = Column(String(24), nullable=False)         # TAKE_CHARGE / ESCALATE / CONFIRM / DISMISS
    to_status = Column(String(32), nullable=True)
    decision = Column(String(16), nullable=True)        # BLOCKED / AUTHORIZED
    justification = Column(Text, nullable=True)

    actor_id = Column(UUID(as_uuid=True), nullable=True)
    actor_label = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
