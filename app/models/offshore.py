"""
Modèle — fuites offshore (ICIJ).

Base SÉPARÉE, consultée à la demande. Trois raisons de ne pas la mêler à
l'index de filtrage :

1. VOLUME — 1,6 million d'enregistrements contre 55 000 pour les sanctions.
   Les y verser multiplierait l'index par trente et dégraderait le
   rapprochement trigramme sur les contrôles quotidiens.
2. NATURE — figurer dans ces fuites n'est PAS un délit. Ce sont des pistes
   d'enquête, jamais des motifs de blocage. Les traiter comme des sanctions
   produirait des alertes injustifiées en masse.
3. LICENCE — les données ICIJ sont sous licence à réciprocité (CC-BY-SA /
   ODbL). Les tenir à l'écart évite de contaminer le reste de la base, et
   l'attribution à l'ICIJ reste explicite.

Données historiques (jusqu'à 2020) : une correspondance signale une structure
ayant existé, pas une situation actuelle.
"""
from __future__ import annotations

import enum

from sqlalchemy import Column, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.models.base import Base


class OffshoreKind(str, enum.Enum):
    ENTITY = "ENTITY"              # société offshore
    OFFICER = "OFFICER"            # personne ou société détentrice / dirigeante
    INTERMEDIARY = "INTERMEDIARY"  # cabinet ayant constitué la structure


class OffshoreRecord(Base):
    __tablename__ = "offshore_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String(32), nullable=False)          # identifiant ICIJ
    kind = Column(Enum(OffshoreKind, name="offshore_kind"), nullable=False)

    name = Column(String, nullable=False)
    name_normalized = Column(String, nullable=False)      # base du rapprochement

    countries = Column(String, nullable=True)
    country_codes = Column(String(128), nullable=True)
    jurisdiction = Column(String(128), nullable=True)
    investigation = Column(String(128), nullable=True)    # Panama Papers, Pandora…
    incorporation_date = Column(String(32), nullable=True)
    status = Column(String(64), nullable=True)
    raw = Column(JSONB, nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_offshore_norm", OffshoreRecord.name_normalized)
Index("ix_offshore_node", OffshoreRecord.node_id)
