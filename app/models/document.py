# app/models/document.py
from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, DateTime, String, BigInteger, Float, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ENUM as PGEnum
from sqlalchemy.sql import func

from app.models.base import Base


class StorageBackend(str, enum.Enum):
    LOCAL = "LOCAL"
    S3 = "S3"


class OCRStatus(str, enum.Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


# ✅ existe en DB: public.ocr_status
OCRStatusPG = PGEnum(
    OCRStatus,
    name="ocr_status",
    create_type=False,  # important: le type existe déjà
)


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    case_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    doc_type = Column(String, nullable=False)

    # ✅ DB stocke en texte => on garde String (pas Enum SQL)
    # Important: default doit être une string ("LOCAL"), pas l'Enum
    storage_backend = Column(
        String,
        nullable=False,
        default=StorageBackend.LOCAL.value,
    )

    object_key = Column(String, nullable=False)
    file_path = Column(String, nullable=False)

    original_filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)

    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String, nullable=False)

    uploaded_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # ✅ enum PG (ocr_status)
    ocr_status = Column(OCRStatusPG, nullable=False, default=OCRStatus.PENDING)

    ocr_confidence = Column(Float, nullable=True)

    # ✅ CRITIQUE: pas de NULL, default Python + default DB
    extracted_fields = Column(
        JSON,
        nullable=False,
        default=dict,           # ✅ côté Python (évite NULL si on oublie)
        server_default="{}",    # ✅ côté DB
    )
