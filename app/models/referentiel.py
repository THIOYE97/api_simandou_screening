"""
Module 1 — Référentiel (TDR §VII).

Référentiel UNIQUE des nomenclatures et paramétrages de la solution LBC/FT :
- pays (avec marquage GAFI / non-coopératif) ;
- secteurs d'activité ;
- catégories de clients ;
- scénarios de risque PARAMÉTRABLES (pièce maîtresse : alimente le scoring M7
  et le moteur d'alertes M6).

Données de référence GLOBALES (partagées, non multi-tenant) : le TDR exige
explicitement un « référentiel unique ».
"""
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base


class ScenarioCategory(str, enum.Enum):
    SANCTIONS = "SANCTIONS"      # correspondance liste de sanction
    PEP = "PEP"                  # personne politiquement exposée
    GEOGRAPHY = "GEOGRAPHY"      # pays à risque / non coopératif
    TRANSACTION = "TRANSACTION"  # seuil / typologie de transaction (KYT)
    BEHAVIOR = "BEHAVIOR"        # comportement atypique (KYT)
    ADVERSE_MEDIA = "ADVERSE_MEDIA"


class Severity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Country(Base):
    """Nomenclature pays + marquage de risque (GAFI, non-coopératif)."""
    __tablename__ = "ref_countries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    iso_code = Column(String(3), nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    is_high_risk = Column(Boolean, nullable=False, default=False)          # liste GAFI (grise/noire)
    is_non_cooperative = Column(Boolean, nullable=False, default=False)    # pays non coopératif
    risk_weight = Column(Integer, nullable=False, default=0)               # contribution au scoring
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class BusinessSector(Base):
    """Nomenclature des secteurs d'activité + pondération de risque."""
    __tablename__ = "ref_business_sectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    risk_weight = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ClientCategory(Base):
    """Segmentation des clients (particulier, PME, PPE, correspondant bancaire...)."""
    __tablename__ = "ref_client_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    base_risk_weight = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Currency(Base):
    """Devise supportée (paramétrable depuis les Réglages)."""
    __tablename__ = "ref_currencies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(3), nullable=False, unique=True, index=True)   # ISO 4217
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=True)
    region = Column(String, nullable=True)      # Guinée, Afrique de l'Ouest, Moyen-Orient…
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RiskScenario(Base):
    """
    Scénario de risque PARAMÉTRABLE (TDR : « segmentation selon un paramétrage
    des scénarii »). Chaque scénario définit un critère (JSONB) et une pondération
    exploités par le Scoring (M7) et le moteur d'Alertes (M6).
    """
    __tablename__ = "ref_risk_scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(Enum(ScenarioCategory, name="scenario_category"), nullable=False)
    severity = Column(Enum(Severity, name="scenario_severity"), nullable=False, default=Severity.MEDIUM)

    # Critère paramétrable, ex :
    #   {"field": "match_score", "op": ">=", "value": 85}
    #   {"field": "country", "op": "in", "value": ["IR", "KP"]}
    #   {"field": "amount", "op": ">", "value": 10000, "currency": "USD"}
    criteria = Column(JSONB, nullable=False, default=dict)

    risk_weight = Column(Integer, nullable=False, default=0)   # points ajoutés au score si déclenché
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
