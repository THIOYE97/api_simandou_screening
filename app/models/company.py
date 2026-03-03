import enum
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Numeric, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, unique=True)

    legal_name = Column(String)
    legal_form = Column(String)
    rccm = Column(String)
    nif = Column(String)
    client_code = Column(String)

    address_full = Column(String)
    city = Column(String)
    commune = Column(String)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class CompanyRoleType(str, enum.Enum):
    DIRECTOR = "DIRECTOR"
    UBO = "UBO"

class CompanyPerson(Base):
    __tablename__ = "company_people"
    __table_args__ = (UniqueConstraint("company_id", "person_id", "role_type", name="uq_company_person_role"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    person_id = Column(UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)

    role_type = Column(Enum(CompanyRoleType, name="company_role_type"), nullable=False)
    ownership_pct = Column(Numeric(5, 2))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
