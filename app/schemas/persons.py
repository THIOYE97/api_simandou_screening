from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import date
from uuid import UUID

class PersonUpsert(BaseModel):
    last_name: Optional[str] = None
    first_names: Optional[str] = None
    date_of_birth: Optional[date] = None
    place_of_birth: Optional[str] = None
    nationality: Optional[str] = None

    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    document_type: Optional[str] = None
    document_number: Optional[str] = None
    document_expiry: Optional[date] = None
    document_issue_country: Optional[str] = None

    ppe_status: Optional[bool] = None
    client_code: Optional[str] = None

class PersonOut(PersonUpsert):
    id: UUID
    entity_id: UUID

    class Config:
        from_attributes = True
