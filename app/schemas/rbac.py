"""Schémas Pydantic — Module 2 RBAC."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RoleIn(BaseModel):
    code: str = Field(..., max_length=32)
    name: str
    description: Optional[str] = None
    permissions: list[str] = Field(default_factory=list)
    active: bool = True


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[list[str]] = None
    active: Optional[bool] = None


class RoleOut(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    code: str
    name: str
    description: Optional[str] = None
    permissions: list[str]
    active: bool

    class Config:
        from_attributes = True


class AssignRoleIn(BaseModel):
    role_code: str
