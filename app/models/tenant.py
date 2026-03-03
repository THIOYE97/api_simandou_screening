# app/models/tenant.py
from __future__ import annotations

from datetime import datetime
from uuid import uuid4, UUID

from sqlalchemy import String, DateTime, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)

    # tu peux garder String si tu n'as pas de type enum PG "tenant_status"
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ACTIVE'"))

    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # relations optionnelles
    users = relationship("User", back_populates="tenant", lazy="selectin")
    invitations = relationship("TenantInvitation", back_populates="tenant", lazy="selectin")
