from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from app.models.case import CaseType, CaseStatus, RiskLevel

class CaseCreate(BaseModel):
    case_type: CaseType

class CaseUpdate(BaseModel):
    status: Optional[CaseStatus] = None
    risk_level: Optional[RiskLevel] = None
    urgent_flag: Optional[bool] = None
    urgent_reason: Optional[str] = None
    assigned_checker: Optional[UUID] = None

class CaseOut(BaseModel):
    id: UUID
    case_type: CaseType
    status: CaseStatus
    risk_level: RiskLevel
    urgent_flag: bool
    urgent_reason: Optional[str] = None
    created_by: Optional[UUID] = None
    assigned_checker: Optional[UUID] = None

    class Config:
        from_attributes = True

class CaseDetail(BaseModel):
    case: CaseOut
    person: Optional[dict] = None
    company: Optional[dict] = None
    company_people: list[dict] = []
    documents: list[dict] = []
