# app/models/user_role.py
from __future__ import annotations

from datetime import datetime
from uuid import uuid4, UUID

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserRole(Base):
    """
    ⚠ Ce modèle NE DÉCRIT PAS la table de production.

    En production, `user_roles` vaut exactement :

        CREATE TABLE public.user_roles (
            user_id uuid NOT NULL,
            role    public.user_role NOT NULL,   -- ENUM, pas varchar
            PRIMARY KEY (user_id, role)
        );

    Ni `id`, ni `tenant_id`, ni `created_at`. L'écart est invisible en test,
    puisque le schéma de test est construit depuis ce modèle : tout code écrit
    d'après ces colonnes passe les tests et échoue en production. Écrire contre
    `information_schema` quand on touche cette table (cf.
    `app/scripts/grant_super_admin.py`), ou aligner le modèle sur la base par
    une migration dédiée.
    """

    __tablename__ = "user_roles"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # OWNER / ADMIN / ANALYST / VIEWER
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role", name="uq_user_roles_tenant_user_role"),
    )
