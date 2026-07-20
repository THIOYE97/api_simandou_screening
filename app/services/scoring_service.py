"""
Service métier — Module 7 Scoring.

Moteur d'évaluation paramétrable :
1. enrichit le contexte (résout les pays à risque, la catégorie client…) ;
2. évalue chaque scénario ACTIF du Référentiel (M1) contre le contexte ;
3. somme les pondérations des scénarios déclenchés (+ base catégorie client) ;
4. classe le risque selon des seuils paramétrables ;
5. persiste un RiskAssessment (historisation).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.referentiel import ClientCategory, Country, RiskScenario
from app.models.scoring import RiskAssessment, RiskClass, SubjectType

# Seuils de classification (paramétrables) : borne haute exclusive.
RISK_THRESHOLDS = [
    (25, RiskClass.LOW),
    (50, RiskClass.MEDIUM),
    (100, RiskClass.HIGH),
]  # au-delà de 100 → CRITICAL


# --- Évaluation d'un critère -------------------------------------------------

def _apply_op(actual: Any, op: str, expected: Any) -> bool:
    try:
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        if op == ">":
            return actual is not None and actual > expected
        if op == ">=":
            return actual is not None and actual >= expected
        if op == "<":
            return actual is not None and actual < expected
        if op == "<=":
            return actual is not None and actual <= expected
        if op == "in":
            return actual in (expected or [])
        if op == "not_in":
            return actual not in (expected or [])
    except TypeError:
        return False
    return False


def _match(criteria: dict, ctx: dict) -> bool:
    """Un critère = {field, op, value}. Champ absent du contexte → non déclenché."""
    field = criteria.get("field")
    op = criteria.get("op", "==")
    expected = criteria.get("value")
    if field is None or field not in ctx:
        return False
    return _apply_op(ctx.get(field), op, expected)


# --- Résolution des pays -----------------------------------------------------
# Le référentiel stocke des codes ISO à 2 lettres. Les agents saisissent
# pourtant souvent l'ISO à 3 lettres (SEN, CIV) ou une abréviation d'usage
# (RCI, RDC), voire un nom sans accent. Sans tolérance, le pays n'est pas
# reconnu et le risque géographique est silencieusement ignoré.

_ALPHA3_TO_ALPHA2 = {
    # Juridictions GAFI
    "IRN": "IR", "PRK": "KP", "MMR": "MM", "DZA": "DZ", "AGO": "AO", "BGR": "BG",
    "BFA": "BF", "CMR": "CM", "CIV": "CI", "HRV": "HR", "COD": "CD", "HTI": "HT",
    "KEN": "KE", "LAO": "LA", "LBN": "LB", "MLI": "ML", "MCO": "MC", "MOZ": "MZ",
    "NAM": "NA", "NPL": "NP", "NGA": "NG", "ZAF": "ZA", "SSD": "SS", "SYR": "SY",
    "TZA": "TZ", "VEN": "VE", "VNM": "VN", "YEM": "YE",
    # Afrique (zone d'activité de la BCRG)
    "GIN": "GN", "SEN": "SN", "GNB": "GW", "GMB": "GM", "GHA": "GH", "TGO": "TG",
    "BEN": "BJ", "NER": "NE", "TCD": "TD", "MRT": "MR", "GAB": "GA", "COG": "CG",
    "CAF": "CF", "GNQ": "GQ", "LBR": "LR", "SLE": "SL", "MAR": "MA", "TUN": "TN",
    "EGY": "EG", "LBY": "LY", "ETH": "ET", "SDN": "SD", "SOM": "SO", "UGA": "UG",
    "RWA": "RW", "BDI": "BI", "ZMB": "ZM", "ZWE": "ZW", "BWA": "BW", "MWI": "MW",
    "MDG": "MG", "MUS": "MU", "CPV": "CV",
    # Principaux partenaires
    "FRA": "FR", "USA": "US", "GBR": "GB", "CHN": "CN", "BEL": "BE", "DEU": "DE",
    "ESP": "ES", "ITA": "IT", "CHE": "CH", "ARE": "AE", "TUR": "TR", "IND": "IN",
    "CAN": "CA", "LUX": "LU", "NLD": "NL", "PRT": "PT",
}

_COUNTRY_ALIASES = {
    "RCI": "CI", "COTE D IVOIRE": "CI", "COTE DIVOIRE": "CI", "IVORY COAST": "CI",
    "RDC": "CD", "DRC": "CD", "CONGO KINSHASA": "CD", "CONGO RDC": "CD",
    "GUINEE": "GN", "GUINEE CONAKRY": "GN", "GUINEA": "GN",
    "ETATS UNIS": "US", "UK": "GB", "ANGLETERRE": "GB", "ROYAUME UNI": "GB",
    "EAU": "AE", "UAE": "AE", "EMIRATS ARABES UNIS": "AE",
    "AFRIQUE DU SUD": "ZA", "SOUTH AFRICA": "ZA",
    "COREE DU NORD": "KP", "NORTH KOREA": "KP", "BIRMANIE": "MM",
}


def _norm_key(value: Any) -> str:
    """Majuscules, sans accents ni ponctuation (« Côte d'Ivoire » → « COTE D IVOIRE »)."""
    txt = unicodedata.normalize("NFD", str(value or ""))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", txt)).strip().upper()


def resolve_country(db: Session, raw: Any) -> Optional[Country]:
    """Résout un pays depuis un code ISO2/ISO3, un alias d'usage ou un nom."""
    key = _norm_key(raw)
    if not key:
        return None

    code = _COUNTRY_ALIASES.get(key) or _ALPHA3_TO_ALPHA2.get(key)
    if not code and len(key) in (2, 3):
        code = key
    if code:
        found = db.execute(
            select(Country).where(func.upper(Country.iso_code) == code)
        ).scalars().first()
        if found:
            return found

    # Repli : comparaison des noms, insensible aux accents et à la ponctuation.
    for country in db.execute(select(Country)).scalars().all():
        if _norm_key(country.name) == key:
            return country
    return None


# --- Enrichissement du contexte ---------------------------------------------

def enrich_context(db: Session, ctx: dict) -> dict:
    """Ajoute des signaux dérivés du Référentiel à partir des données brutes."""
    out = dict(ctx)

    raw = out.get("country")
    if raw:
        country = resolve_country(db, raw)
        if country:
            out.setdefault("country_is_high_risk", country.is_high_risk)
            out.setdefault("country_is_non_cooperative", country.is_non_cooperative)
            out["_country_weight"] = country.risk_weight if country.active else 0

    return out


# --- Classification ----------------------------------------------------------

def classify(total: int) -> RiskClass:
    for upper, cls in RISK_THRESHOLDS:
        if total < upper:
            return cls
    return RiskClass.CRITICAL


# --- Scoring principal -------------------------------------------------------

def score_subject(
    db: Session,
    subject_type: SubjectType,
    context: dict,
    subject_ref: Optional[str] = None,
    subject_label: Optional[str] = None,
    created_by: Optional[UUID] = None,
    tenant_id: Optional[UUID] = None,
    persist: bool = True,
) -> RiskAssessment:
    ctx = enrich_context(db, context)

    # base : pondération de la catégorie de client
    base = 0
    cat_code = ctx.get("client_category")
    if cat_code:
        cat = db.execute(
            select(ClientCategory).where(ClientCategory.code == cat_code)
        ).scalars().first()
        if cat:
            base = cat.base_risk_weight

    scenarios = db.execute(
        select(RiskScenario).where(RiskScenario.active.is_(True))
    ).scalars().all()

    triggered: list[dict] = []
    total = base
    for sc in scenarios:
        if _match(sc.criteria or {}, ctx):
            triggered.append({
                "code": sc.code,
                "name": sc.name,
                "category": sc.category.value,
                "severity": sc.severity.value,
                "weight": sc.risk_weight,
            })
            total += sc.risk_weight

    total = min(total, 100)  # score plafonné à 100
    assessment = RiskAssessment(
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_ref=subject_ref,
        subject_label=subject_label,
        total_score=total,
        risk_class=classify(total),
        triggered=triggered,
        context={k: v for k, v in ctx.items() if not k.startswith("_")},
        created_by=created_by,
    )
    if persist:
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
    return assessment


def list_assessments(
    db: Session,
    subject_ref: Optional[str] = None,
    limit: int = 50,
) -> list[RiskAssessment]:
    stmt = select(RiskAssessment).order_by(RiskAssessment.created_at.desc()).limit(limit)
    if subject_ref:
        stmt = select(RiskAssessment).where(
            RiskAssessment.subject_ref == subject_ref
        ).order_by(RiskAssessment.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())
