import enum
import uuid
from sqlalchemy import Column, Text, String, DateTime, Boolean, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base


class CaseType(str, enum.Enum):
    KYC = "KYC"
    KYS = "KYS"


class CaseStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Case(Base):
    __tablename__ = "cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_type = Column(Enum(CaseType, name="case_type"), nullable=False)
    status = Column(Enum(CaseStatus, name="case_status"), nullable=False, default=CaseStatus.DRAFT)
    risk_level = Column(Enum(RiskLevel, name="risk_level"), nullable=False, default=RiskLevel.LOW)

    urgent_flag = Column(Boolean, nullable=False, default=False)
    urgent_reason = Column(String)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_checker = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    last_screening_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # --- Sumsub fields (Option A: externalUserId == Case.id) ---
    sumsub_applicant_id = Column(Text, nullable=True, index=True)
    sumsub_review_status = Column(Text, nullable=True)
    sumsub_review_answer = Column(Text, nullable=True)
    sumsub_last_event_at = Column(DateTime(timezone=True), nullable=True)
    sumsub_snapshot = Column(JSONB, nullable=True)
