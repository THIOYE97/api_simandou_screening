"""
Module 2 — RBAC : définition des rôles et de leurs habilitations (permissions).

L'AFFECTATION rôle→utilisateur réutilise la table existante `user_roles`
(colonne `role`). Ici on stocke la DÉFINITION rôle→permissions, paramétrable.
"""
import uuid

from sqlalchemy import Boolean, Column, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base


class UserRoleAssignment(Base):
    """
    Affectation rôle → utilisateur, propre au module RBAC.

    Table dédiée (et non la table legacy `user_roles`, dont le schéma a divergé
    du modèle historique — cf. REFACTOR.md), pour un couplage propre et stable.
    """
    __tablename__ = "rbac_user_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role_code", name="uq_rbac_user_roles"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    role_code = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Role(Base):
    __tablename__ = "rbac_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_rbac_roles_tenant_code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # tenant_id NULL = rôle global par défaut ; sinon rôle propre à un tenant
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    code = Column(String(32), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    permissions = Column(JSONB, nullable=False, default=list)  # ["alerts:manage", ...] ou ["*"]
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
