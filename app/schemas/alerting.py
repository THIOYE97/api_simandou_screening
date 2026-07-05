"""Schémas Pydantic — Module 6 Alerte."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.alerting import AlertSeverity, AlertSource, AlertStatus


class RuleIn(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    source: AlertSource = AlertSource.SCORING
    severity: AlertSeverity = AlertSeverity.MEDIUM
    condition: dict[str, Any] = Field(default_factory=dict)
    auto_escalate: bool = False
    active: bool = True


class RuleOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    source: AlertSource
    severity: AlertSeverity
    condition: dict[str, Any]
    auto_escalate: bool
    active: bool

    class Config:
        from_attributes = True


class AlertOut(BaseModel):
    id: UUID
    source: AlertSource
    severity: AlertSeverity
    status: AlertStatus
    title: str
    rule_code: Optional[str] = None
    subject_ref: Optional[str] = None
    subject_label: Optional[str] = None
    risk_assessment_id: Optional[UUID] = None
    detail: dict[str, Any]
    assigned_to: Optional[UUID] = None
    resolution: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class StatusUpdate(BaseModel):
    status: AlertStatus
    resolution: Optional[str] = None


class AssignUpdate(BaseModel):
    assignee: UUID
