"""Schémas Pydantic — Module 5 KYT + Déclaration de soupçon."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.kyt import (
    Channel,
    Direction,
    SARDecision,
    SARStatus,
    SourceSystem,
)
from app.models.scoring import RiskClass


class TransactionIn(BaseModel):
    external_ref: Optional[str] = None
    source_system: SourceSystem = SourceSystem.MANUAL
    direction: Direction = Direction.IN
    channel: Channel = Channel.WIRE
    amount: Decimal
    currency: str = "USD"
    customer_ref: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_country: Optional[str] = None
    value_date: Optional[datetime] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class TransactionOut(BaseModel):
    id: UUID
    external_ref: Optional[str] = None
    source_system: SourceSystem
    direction: Direction
    channel: Channel
    amount: Decimal
    currency: str
    customer_ref: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_country: Optional[str] = None
    risk_assessment_id: Optional[UUID] = None
    risk_class: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IngestResult(BaseModel):
    transaction: TransactionOut
    risk_class: RiskClass
    total_score: int
    triggered: list[dict[str, Any]]
    alerts_created: int
    # Parties filtrées contre les listes (émetteur / bénéficiaire), avec leur
    # résultat — y compris « vérifié, aucune correspondance ».
    parties: list[dict[str, Any]] = Field(default_factory=list)


class SARIn(BaseModel):
    subject_ref: Optional[str] = None
    subject_label: Optional[str] = None
    reason: str
    narrative: Optional[str] = None
    related_alert_id: Optional[UUID] = None
    related_transaction_ids: list[UUID] = Field(default_factory=list)


class SARUpdate(BaseModel):
    status: Optional[SARStatus] = None
    decision: Optional[SARDecision] = None
    narrative: Optional[str] = None


class SAROut(BaseModel):
    id: UUID
    subject_ref: Optional[str] = None
    subject_label: Optional[str] = None
    reason: str
    narrative: Optional[str] = None
    status: SARStatus
    decision: SARDecision
    related_alert_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True
