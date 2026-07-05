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


# --- Enrichissement du contexte ---------------------------------------------

def enrich_context(db: Session, ctx: dict) -> dict:
    """Ajoute des signaux dérivés du Référentiel à partir des données brutes."""
    out = dict(ctx)

    raw = out.get("country")
    if raw:
        val = str(raw).strip()
        # Résolution tolérante : par code ISO (ML) OU par nom (Mali, mali)
        country = db.execute(
            select(Country).where(func.upper(Country.iso_code) == val.upper())
        ).scalars().first()
        if not country:
            country = db.execute(
                select(Country).where(func.lower(Country.name) == val.lower())
            ).scalars().first()
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
