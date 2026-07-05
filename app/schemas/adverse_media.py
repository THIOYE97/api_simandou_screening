"""Schémas Pydantic — Adverse media."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.adverse_media import AdverseMediaCategory


class ScreenRequest(BaseModel):
    name: str
    threshold: int = 65


class RecordIn(BaseModel):
    entity_name: str
    category: AdverseMediaCategory
    source: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None


class RecordOut(BaseModel):
    id: UUID
    entity_name: str
    category: AdverseMediaCategory
    source: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True
