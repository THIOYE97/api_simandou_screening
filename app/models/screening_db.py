# app/models/screening_db.py
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    Integer,
    SmallInteger,
    Text,
    Date,
    TIMESTAMP,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy import Enum as SAEnum

from app.models.base import Base


# -----------------------------------------------------------------------------
# Enums (DB types already exist => create_type=False)
# -----------------------------------------------------------------------------
EntityType = SAEnum("person", "company", name="entity_type", create_type=False)

RiskLevel = SAEnum("LOW", "MEDIUM", "HIGH", name="risk_level", create_type=False)

RecordType = SAEnum(
    "SANCTION",
    "PEP",
    "ADVERSE_MEDIA",
    "BAN",
    name="record_type",
    create_type=False,
)

MatchBand = SAEnum("STRONG", "POSSIBLE", "WEAK", name="match_band", create_type=False)

ActionType = SAEnum("PASS", "MANUAL_REVIEW", "BLOCK", name="action_type", create_type=False)


# -----------------------------------------------------------------------------
# Core entities
# -----------------------------------------------------------------------------
class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    entity_type: Mapped[str] = mapped_column(EntityType, nullable=False)
    primary_name: Mapped[str] = mapped_column(Text, nullable=False)
    country_focus: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(RiskLevel, nullable=False)

    created_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    names: Mapped[list["EntityName"]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    source_records: Mapped[list["SourceRecord"]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EntityName(Base):
    __tablename__ = "entity_names"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        index=True,
    )

    name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name_tokens: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name_type: Mapped[str] = mapped_column(Text, nullable=False)  # PRIMARY/ALIAS/AKA/TRANSLIT

    created_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    entity: Mapped["Entity"] = relationship(back_populates="names")


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        index=True,
    )

    record_type: Mapped[str] = mapped_column(RecordType, nullable=False)
    listed_on: Mapped[Any | None] = mapped_column(Date)
    unlisted_on: Mapped[Any | None] = mapped_column(Date)

    program: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    evidence_urls: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    entity: Mapped["Entity"] = relationship(back_populates="source_records")


# -----------------------------------------------------------------------------
# Screening tables (UPDATED to match your DB)
# -----------------------------------------------------------------------------
class ScreeningRequest(Base):
    __tablename__ = "screening_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    client_id: Mapped[str | None] = mapped_column(Text)

    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ✅ NEW columns present in DB
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="INTERNAL")

    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DONE")

    completed_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ✅ Relationships fixed
    results: Mapped[list["ScreeningResult"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    matches: Mapped[list["ScreeningMatch"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ScreeningResult(Base):
    __tablename__ = "screening_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("screening_requests.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # ✅ tenant_id exists in DB (you confirmed)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    request: Mapped["ScreeningRequest"] = relationship(back_populates="results")

    risk_level: Mapped[str] = mapped_column(RiskLevel, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..100
    recommended_action: Mapped[str] = mapped_column(ActionType, nullable=False)

    decided_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="SYSTEM")
    decided_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text)


class ScreeningMatch(Base):
    __tablename__ = "screening_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("screening_requests.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # ✅ tenant_id exists in DB (your insert SQL already uses it)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    request: Mapped["ScreeningRequest"] = relationship(back_populates="matches")

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_records.id", ondelete="SET NULL"),
        nullable=True,
    )

    match_score: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..100
    match_band: Mapped[str] = mapped_column(MatchBand, nullable=False)
    reasons: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
