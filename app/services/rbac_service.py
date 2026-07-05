"""
Service métier — Module 2 RBAC.

Calcule les permissions effectives d'un utilisateur (rôles `user_roles` →
définitions `rbac_roles`), gère les rôles (CRUD paramétrable) et l'affectation
de rôles aux utilisateurs.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.permissions import DEFAULT_ROLES
from app.models.rbac import Role, UserRoleAssignment


def user_role_codes(db: Session, user_id: UUID, tenant_id: Optional[UUID]) -> list[str]:
    stmt = select(UserRoleAssignment.role_code).where(UserRoleAssignment.user_id == user_id)
    if tenant_id:
        stmt = stmt.where(UserRoleAssignment.tenant_id == tenant_id)
    return list(db.execute(stmt).scalars().all())


def get_user_permissions(db: Session, user_id: UUID, tenant_id: Optional[UUID]) -> set[str]:
    """Union des permissions des rôles de l'utilisateur (rôle tenant > rôle global)."""
    codes = user_role_codes(db, user_id, tenant_id)
    if not codes:
        return set()
    stmt = select(Role).where(
        Role.code.in_(codes),
        Role.active.is_(True),
        or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
    )
    perms: set[str] = set()
    for role in db.execute(stmt).scalars().all():
        perms.update(role.permissions or [])
    return perms


# --- Paramétrage des rôles ---------------------------------------------------

def list_roles(db: Session, tenant_id: Optional[UUID] = None) -> list[Role]:
    stmt = select(Role).where(or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None))).order_by(Role.code)
    return list(db.execute(stmt).scalars().all())


def create_role(db: Session, data: dict) -> Role:
    obj = Role(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_role(db: Session, role_id: UUID, data: dict) -> Optional[Role]:
    obj = db.get(Role, role_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


def seed_roles(db: Session) -> int:
    """Insère les rôles par défaut (globaux, tenant_id NULL). Idempotent."""
    existing = {r.code for r in db.execute(
        select(Role).where(Role.tenant_id.is_(None))
    ).scalars().all()}
    n = 0
    for code, spec in DEFAULT_ROLES.items():
        if code not in existing:
            db.add(Role(
                tenant_id=None, code=code, name=spec["name"],
                description=spec["description"], permissions=spec["permissions"],
            ))
            n += 1
    db.commit()
    return n


# --- Affectation rôle → utilisateur (réutilise user_roles) -------------------

def assign_role(db: Session, user_id: UUID, tenant_id: UUID, role_code: str) -> None:
    exists = db.execute(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.tenant_id == tenant_id,
            UserRoleAssignment.role_code == role_code,
        )
    ).scalars().first()
    if exists:
        return
    db.add(UserRoleAssignment(user_id=user_id, tenant_id=tenant_id, role_code=role_code))
    db.commit()


def revoke_role(db: Session, user_id: UUID, tenant_id: UUID, role_code: str) -> None:
    obj = db.execute(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.tenant_id == tenant_id,
            UserRoleAssignment.role_code == role_code,
        )
    ).scalars().first()
    if obj:
        db.delete(obj)
        db.commit()
