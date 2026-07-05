"""Schémas Pydantic — Module 7 Scoring."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.scoring import RiskClass, SubjectType


class ScoreRequest(BaseModel):
    subject_type: SubjectType = SubjectType.PERSON
    subject_ref: Optional[str] = None
    subject_label: Optional[str] = None
    # Signaux : match_score, is_pep, country (ISO), client_category, amount, channel, pattern...
    context: dict[str, Any] = Field(default_factory=dict)


class AssessmentOut(BaseModel):
    id: UUID
    subject_type: SubjectType
    subject_ref: Optional[str] = None
    subject_label: Optional[str] = None
    total_score: int
    risk_class: RiskClass
    triggered: list[dict[str, Any]]
    context: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
