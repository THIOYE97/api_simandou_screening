"""
Modèle — Bénéficiaires effectifs (BE).

Registre INTERNE, alimenté par les déclarations des assujettis. C'est le socle
du dispositif : aucune source publique ne couvre la Guinée ni la zone OHADA en
bénéficiaires effectifs (le RCCM s'arrête aux dirigeants). Les sources externes
libres de droits (registre britannique PSC, GLEIF, ICIJ) viendront en
enrichissement, pas en fondation.

Structure alignée sur le Beneficial Ownership Data Standard (BODS) :
une déclaration porte sur une personne morale ; ses membres forment une CHAÎNE
de détention (`parent_id`), car le bénéficiaire effectif est rarement détenteur
direct — il se tient au bout d'un enchaînement de sociétés.
"""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text,
)
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base


class PartyKind(str, enum.Enum):
    """Un maillon de la chaîne est soit une personne physique, soit une société."""
    PERSON = "PERSON"
    ENTITY = "ENTITY"


class ControlNature(str, enum.Enum):
    """Nature du contrôle exercé (vocabulaire LBC/FT)."""
    CAPITAL = "CAPITAL"            # détention du capital
    VOTING_RIGHTS = "VOTING_RIGHTS"  # droits de vote
    EFFECTIVE_CONTROL = "EFFECTIVE_CONTROL"  # contrôle par tout autre moyen
    LEGAL_REPRESENTATIVE = "LEGAL_REPRESENTATIVE"  # dirigeant (BE par défaut)


class UboDeclaration(Base):
    """Déclaration de bénéficiaires effectifs d'une personne morale."""
    __tablename__ = "ubo_declarations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    company_name = Column(String, nullable=False)
    company_ref = Column(String, nullable=True)        # RCCM, NIF…
    company_country = Column(String(64), nullable=True)
    case_id = Column(UUID(as_uuid=True), nullable=True)  # dossier rattaché

    # Dernière évaluation de risque produite pour cette personne morale.
    risk_assessment_id = Column(UUID(as_uuid=True), nullable=True)
    last_screened_at = Column(DateTime(timezone=True), nullable=True)

    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UboMember(Base):
    """
    Un maillon de la chaîne de détention.

    `parent_id` NULL = détenteur direct de la personne morale déclarée.
    Sinon, le membre détient son parent (donc indirectement la société).
    """
    __tablename__ = "ubo_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    declaration_id = Column(
        UUID(as_uuid=True), ForeignKey("ubo_declarations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    parent_id = Column(
        UUID(as_uuid=True), ForeignKey("ubo_members.id", ondelete="CASCADE"), nullable=True,
    )

    kind = Column(Enum(PartyKind, name="ubo_party_kind"), nullable=False, default=PartyKind.PERSON)
    full_name = Column(String, nullable=False)
    nationality = Column(String(64), nullable=True)
    country = Column(String(64), nullable=True)
    date_of_birth = Column(String(32), nullable=True)
    identifier = Column(String, nullable=True)         # pièce d'identité / RCCM

    ownership_percent = Column(Numeric(6, 3), nullable=True)
    control_nature = Column(
        Enum(ControlNature, name="ubo_control_nature"),
        nullable=False, default=ControlNature.CAPITAL,
    )
    # Bénéficiaire effectif retenu (seuil de 25 % ou contrôle par autre moyen).
    is_beneficial_owner = Column(Boolean, nullable=False, default=False)

    # Résultat du dernier filtrage contre les listes.
    screening_request_id = Column(UUID(as_uuid=True), nullable=True)
    match_score = Column(Integer, nullable=True)
    is_pep = Column(Boolean, nullable=False, default=False)
    screened_at = Column(DateTime(timezone=True), nullable=True)
    matches = Column(JSONB, nullable=False, server_default="[]")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
