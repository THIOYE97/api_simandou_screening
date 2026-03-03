from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from app.models.company import CompanyRoleType

class CompanyUpsert(BaseModel):
    legal_name: Optional[str] = None
    legal_form: Optional[str] = None
    rccm: Optional[str] = None
    nif: Optional[str] = None
    client_code: Optional[str] = None
    address_full: Optional[str] = None
    city: Optional[str] = None
    commune: Optional[str] = None

class CompanyOut(CompanyUpsert):
    id: UUID
    entity_id: UUID

    class Config:
        from_attributes = True

class CompanyPersonCreate(BaseModel):
    person_entity_id: UUID
    role_type: CompanyRoleType
    ownership_pct: Optional[float] = None
