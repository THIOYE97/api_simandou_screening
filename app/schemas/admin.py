from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class EntityNameOut(BaseModel):
    id: int
    name_raw: str
    name_normalized: str
    is_primary: bool
    name_type: str


class SourceRecordOut(BaseModel):
    id: str
    source_id: int
    source_ref: str
    record_type: str
    program: Optional[str] = None
    listed_on: Optional[str] = None
    unlisted_on: Optional[str] = None
    summary: Optional[str] = None
    evidence_urls: Optional[list[str]] = None
    raw_payload: Optional[dict[str, Any]] = None


class EntityOut(BaseModel):
    id: str
    entity_type: str
    primary_name: str
    country_focus: Optional[str] = None
    risk_level: str
    created_at: str
    updated_at: str
    names: list[EntityNameOut] = Field(default_factory=list)
    sources: list[SourceRecordOut] = Field(default_factory=list)


class EntitySearchHit(BaseModel):
    entity_id: str
    entity_type: str
    primary_name: str
    risk_level: str
    best_norm: str
    similarity: float
    score_hint: int  # 0..100 (juste indicatif)
    source_count: int
    names_count: int


class Paged(BaseModel):
    items: list[Any]
    limit: int
    offset: int
    total: int


class ScreeningRequestListItem(BaseModel):
    id: str
    client_id: Optional[str] = None
    created_at: str
    request_payload: dict[str, Any]


class ScreeningMatchOut(BaseModel):
    id: int
    request_id: str
    entity_id: str
    source_record_id: Optional[str] = None
    match_score: int
    match_band: str
    reasons: dict[str, Any]
    created_at: str


class ScreeningResultOut(BaseModel):
    id: str
    request_id: str
    risk_level: str
    confidence: int
    recommended_action: str
    decided_by: str
    decided_at: str
    notes: Optional[str] = None


class ScreeningRequestDetail(BaseModel):
    request: ScreeningRequestListItem
    result: Optional[ScreeningResultOut] = None
    matches: list[ScreeningMatchOut] = Field(default_factory=list)
