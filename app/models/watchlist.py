import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class WatchlistEntity(Base):
    __tablename__ = "watchlist_entity"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    entity_type: Mapped[str] = mapped_column(String(16), default="PERSON")  # PERSON|ORG
    primary_name: Mapped[str] = mapped_column(String(256), index=True)
    normalized_name: Mapped[str] = mapped_column(String(256), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    aliases: Mapped[list["WatchlistAlias"]] = relationship(back_populates="entity", cascade="all, delete-orphan")

class WatchlistAlias(Base):
    __tablename__ = "watchlist_alias"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("watchlist_entity.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(256), index=True)
    normalized_name: Mapped[str] = mapped_column(String(256), index=True)

    entity: Mapped["WatchlistEntity"] = relationship(back_populates="aliases")

class WatchlistSourceRecord(Base):
    __tablename__ = "watchlist_source_record"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source_code: Mapped[str] = mapped_column(String(32), index=True)   # UN/EU/SGG/...
    source_ref: Mapped[str] = mapped_column(String(128), index=True)   # unique key in source
    record_type: Mapped[str] = mapped_column(String(32), default="SANCTION")

    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("watchlist_entity.id", ondelete="SET NULL"), index=True, nullable=True)
    dataset_version: Mapped[str] = mapped_column(String(64), index=True)

    raw: Mapped[dict] = mapped_column(JSONB)  # record brut (JSON)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
