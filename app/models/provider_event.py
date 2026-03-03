# app/models/provider_event.py

from __future__ import annotations

from sqlalchemy import Column, BigInteger, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.models.base import Base


class ProviderEvent(Base):
    __tablename__ = "provider_events"

    id = Column(BigInteger, primary_key=True, index=True)

    provider = Column(Text, nullable=False)
    external_id = Column(Text, nullable=True)          # ex: applicantId
    event_type = Column(Text, nullable=False)          # ex: applicantReviewed
    payload = Column(JSONB, nullable=False)            # jsonb
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    provider_event_id = Column(Text, nullable=True)    # for dedupe (correlationId etc.)
