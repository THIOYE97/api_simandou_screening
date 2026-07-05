"""
Service métier — Module 5 KYT (comportements atypiques) + Déclaration de soupçon.

Pipeline d'une transaction :
1. ingestion (depuis T24/SWIFT/ACH/RTGS ou manuel) ;
2. construction du contexte + détection de motifs (structuring) ;
3. scoring (M7) en sujet TRANSACTION → historisation ;
4. génération d'alertes (M6).
La Déclaration de soupçon (SAR) est gérée séparément (workflow Cellule Conformité).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.kyt import (
    SARDecision,
    SARStatus,
    SourceSystem,
    SuspiciousActivityReport,
    Transaction,
)
from app.models.scoring import SubjectType
from app.services import alerting_service, scoring_service

# Paramètres de détection (paramétrables — alignés sur le référentiel M1)
STRUCTURING_THRESHOLD = Decimal("10000")
STRUCTURING_WINDOW_DAYS = 7
STRUCTURING_MIN_COUNT = 3


def _detect_structuring(db: Session, txn: Transaction) -> bool:
    """
    Fractionnement : plusieurs opérations juste sous le seuil de déclaration
    par le même client sur une fenêtre glissante.
    """
    if not txn.customer_ref:
        return False
    lower = STRUCTURING_THRESHOLD * Decimal("0.5")
    since = datetime.now(timezone.utc) - timedelta(days=STRUCTURING_WINDOW_DAYS)
    count = db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.customer_ref == txn.customer_ref,
            Transaction.amount >= lower,
            Transaction.amount < STRUCTURING_THRESHOLD,
            Transaction.created_at >= since,
        )
    ).scalar_one()
    # `count` inclut la transaction courante (déjà persistée avant analyse)
    return count >= STRUCTURING_MIN_COUNT


def analyze_transaction(db: Session, txn: Transaction):
    """Construit le contexte, score la transaction et génère les alertes."""
    ctx = {
        "amount": float(txn.amount),
        "channel": txn.channel.value,
        "source_system": txn.source_system.value,
    }
    if txn.counterparty_country:
        ctx["country"] = txn.counterparty_country
    if _detect_structuring(db, txn):
        ctx["pattern"] = "structuring"

    # Libellé lisible : le CLIENT concerné en priorité (nom/prénom), pas un ID.
    label = (txn.customer_ref or "").strip() or (
        f"Opération {txn.external_ref}" if txn.external_ref else f"Opération {txn.amount} {txn.currency}"
    )
    assessment = scoring_service.score_subject(
        db,
        subject_type=SubjectType.TRANSACTION,
        context=ctx,
        subject_ref=txn.customer_ref or txn.external_ref,
        subject_label=label,
        tenant_id=txn.tenant_id,
        persist=True,
    )
    txn.risk_assessment_id = assessment.id
    db.commit()

    alerts = alerting_service.generate_from_assessment(db, assessment)
    return assessment, alerts


def ingest_transaction(db: Session, data: dict, tenant_id: Optional[UUID] = None):
    """Persiste une transaction puis l'analyse. Retourne (txn, assessment, alerts)."""
    txn = Transaction(tenant_id=tenant_id, **data)
    db.add(txn)
    db.commit()
    db.refresh(txn)
    assessment, alerts = analyze_transaction(db, txn)
    db.refresh(txn)
    return txn, assessment, alerts


def get_transaction_detail(db: Session, txn_id: UUID) -> Optional[dict]:
    """Une opération + son évaluation de risque (score, scénarios déclenchés)."""
    from app.models.scoring import RiskAssessment

    t = db.get(Transaction, txn_id)
    if not t:
        return None
    assessment = None
    if t.risk_assessment_id:
        a = db.get(RiskAssessment, t.risk_assessment_id)
        if a:
            assessment = {
                "total_score": a.total_score,
                "risk_class": a.risk_class.value if hasattr(a.risk_class, "value") else a.risk_class,
                "triggered": a.triggered or [],
                "context": a.context or {},
            }
    return {
        "id": str(t.id),
        "external_ref": t.external_ref,
        "source_system": t.source_system.value if hasattr(t.source_system, "value") else t.source_system,
        "direction": t.direction.value if hasattr(t.direction, "value") else t.direction,
        "channel": t.channel.value if hasattr(t.channel, "value") else t.channel,
        "amount": str(t.amount),
        "currency": t.currency,
        "customer_ref": t.customer_ref,
        "counterparty_name": t.counterparty_name,
        "counterparty_country": t.counterparty_country,
        "decision": getattr(t, "decision", None),
        "value_date": t.value_date.isoformat() if t.value_date else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "assessment": assessment,
        "events": alerting_service.list_events(db, subject_id=str(t.id)),
    }


def list_transactions(
    db: Session,
    customer_ref: Optional[str] = None,
    source_system: Optional[SourceSystem] = None,
    limit: int = 50,
) -> list[Transaction]:
    from app.models.scoring import RiskAssessment

    stmt = select(Transaction).order_by(Transaction.created_at.desc()).limit(limit)
    if customer_ref:
        stmt = stmt.where(Transaction.customer_ref == customer_ref)
    if source_system:
        stmt = stmt.where(Transaction.source_system == source_system)
    txns = list(db.execute(stmt).scalars().all())

    # Enrichit chaque opération avec son niveau de risque (évaluation liée).
    ids = [t.risk_assessment_id for t in txns if t.risk_assessment_id]
    classes: dict = {}
    if ids:
        for aid, rc in db.execute(
            select(RiskAssessment.id, RiskAssessment.risk_class).where(RiskAssessment.id.in_(ids))
        ).all():
            classes[aid] = rc.value if hasattr(rc, "value") else rc
    for t in txns:
        setattr(t, "risk_class", classes.get(t.risk_assessment_id))
    return txns


# --- Déclaration de soupçon (SAR) -------------------------------------------

def create_sar(db: Session, data: dict, created_by: Optional[UUID] = None,
               tenant_id: Optional[UUID] = None) -> SuspiciousActivityReport:
    sar = SuspiciousActivityReport(created_by=created_by, tenant_id=tenant_id, **data)
    db.add(sar)
    db.commit()
    db.refresh(sar)
    return sar


_SAR_TRANSITIONS = {
    SARStatus.DRAFT: {SARStatus.SUBMITTED},
    SARStatus.SUBMITTED: {SARStatus.UNDER_REVIEW},
    SARStatus.UNDER_REVIEW: {SARStatus.DECIDED},
    SARStatus.DECIDED: set(),
}


def update_sar(
    db: Session,
    sar_id: UUID,
    status: Optional[SARStatus] = None,
    decision: Optional[SARDecision] = None,
    reviewed_by: Optional[UUID] = None,
    narrative: Optional[str] = None,
) -> Optional[SuspiciousActivityReport]:
    sar = db.get(SuspiciousActivityReport, sar_id)
    if not sar:
        return None
    if status and status != sar.status:
        if status not in _SAR_TRANSITIONS.get(sar.status, set()):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=409,
                detail=f"Transition SAR {sar.status.value} → {status.value} non autorisée",
            )
        sar.status = status
    if decision:
        sar.decision = decision
    if narrative is not None:
        sar.narrative = narrative
    if reviewed_by:
        sar.reviewed_by = reviewed_by
    db.commit()
    db.refresh(sar)
    return sar


def list_sars(db: Session, status: Optional[SARStatus] = None, limit: int = 50):
    stmt = select(SuspiciousActivityReport).order_by(
        SuspiciousActivityReport.created_at.desc()
    ).limit(limit)
    if status:
        stmt = stmt.where(SuspiciousActivityReport.status == status)
    return list(db.execute(stmt).scalars().all())
