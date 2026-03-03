import uuid
from sqlalchemy import Column, String, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base

class Person(Base):
    __tablename__ = "persons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, unique=True)

    last_name = Column(String)
    first_names = Column(String)
    date_of_birth = Column(Date)
    place_of_birth = Column(String)
    nationality = Column(String)

    address = Column(String)
    phone = Column(String)
    email = Column(String)

    document_type = Column(String)
    document_number = Column(String)
    document_expiry = Column(Date)
    document_issue_country = Column(String)

    ppe_status = Column(Boolean)
    client_code = Column(String)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
