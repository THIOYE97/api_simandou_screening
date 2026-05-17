# app/models/refresh_token.py
from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class RefreshToken(Base):
    """
    Refresh tokens persistés pour :
      - autoriser le renouvellement de l'access token
      - révoquer une session (logout, fuite, désactivation user)

    Le token complet n'est PAS stocké : on garde son SHA-256 (côté serveur,
    type stockage "hashed bearer"). Côté client, on lui rend le token clair
    une seule fois à la création.
    """

    __tablename__ = "refresh_tokens"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # SHA-256 du token clair (64 hex chars). Indexé pour lookup O(log n).
    token_hash = Column(String(64), nullable=False, unique=True, index=True)

    issued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Si non NULL → token révoqué. On garde la ligne pour l'audit.
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(Text, nullable=True)  # "logout" | "rotated" | "compromised" | "user_disabled"

    # Contexte client (pour audit/forensic)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_refresh_tokens_user_active", "user_id", "revoked_at"),
        Index("ix_refresh_tokens_expires", "expires_at"),
    )
