# app/models/user.py
from __future__ import annotations

import uuid
from sqlalchemy import Column, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ✅ email unique globalement
    email = Column(Text, unique=True, nullable=False, index=True)

    full_name = Column(Text, nullable=False)
    password_hash = Column(Text)

    is_active = Column(Boolean, nullable=False, server_default="true")

    # ✅ multi-tenant
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True, index=True)
    tenant = relationship("Tenant", lazy="joined")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
