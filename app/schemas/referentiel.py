"""Schémas Pydantic — Module 1 Référentiel."""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.referentiel import ScenarioCategory, Severity


# --- Country ---
class CountryIn(BaseModel):
    iso_code: str = Field(..., min_length=2, max_length=3)
    name: str
    is_high_risk: bool = False
    is_non_cooperative: bool = False
    risk_weight: int = 0
    active: bool = True


class CountryUpdate(BaseModel):
    name: Optional[str] = None
    is_high_risk: Optional[bool] = None
    is_non_cooperative: Optional[bool] = None
    risk_weight: Optional[int] = None
    active: Optional[bool] = None


class CountryOut(BaseModel):
    id: UUID
    iso_code: str
    name: str
    is_high_risk: bool
    is_non_cooperative: bool
    risk_weight: int
    active: bool

    class Config:
        from_attributes = True


# --- BusinessSector ---
class SectorIn(BaseModel):
    code: str
    name: str
    risk_weight: int = 0
    active: bool = True


class SectorUpdate(BaseModel):
    name: Optional[str] = None
    risk_weight: Optional[int] = None
    active: Optional[bool] = None


class SectorOut(BaseModel):
    id: UUID
    code: str
    name: str
    risk_weight: int
    active: bool

    class Config:
        from_attributes = True


# --- ClientCategory ---
class ClientCategoryIn(BaseModel):
    code: str
    name: str
    base_risk_weight: int = 0
    active: bool = True


class ClientCategoryUpdate(BaseModel):
    name: Optional[str] = None
    base_risk_weight: Optional[int] = None
    active: Optional[bool] = None


class ClientCategoryOut(BaseModel):
    id: UUID
    code: str
    name: str
    base_risk_weight: int
    active: bool

    class Config:
        from_attributes = True


# --- Currency ---
class CurrencyIn(BaseModel):
    code: str = Field(..., min_length=3, max_length=3)
    name: str
    symbol: Optional[str] = None
    region: Optional[str] = None
    active: bool = True


class CurrencyUpdate(BaseModel):
    name: Optional[str] = None
    symbol: Optional[str] = None
    region: Optional[str] = None
    active: Optional[bool] = None


class CurrencyOut(BaseModel):
    id: UUID
    code: str
    name: str
    symbol: Optional[str] = None
    region: Optional[str] = None
    active: bool

    class Config:
        from_attributes = True


# --- RiskScenario ---
class ScenarioIn(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    category: ScenarioCategory
    severity: Severity = Severity.MEDIUM
    criteria: dict[str, Any] = Field(default_factory=dict)
    risk_weight: int = 0
    active: bool = True


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[ScenarioCategory] = None
    severity: Optional[Severity] = None
    criteria: Optional[dict[str, Any]] = None
    risk_weight: Optional[int] = None
    active: Optional[bool] = None


class ScenarioOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    category: ScenarioCategory
    severity: Severity
    criteria: dict[str, Any]
    risk_weight: int
    active: bool

    class Config:
        from_attributes = True
