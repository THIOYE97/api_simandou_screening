"""
Service métier — Module 8 Reportings.

Rapports d'inventaire (lecture seule) sur les personnes et transactions à risque,
alimentés par les modules Scoring (M7), Alerte (M6) et KYT (M5).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alerting import Alert, AlertSeverity, AlertStatus
from app.models.kyt import SARStatus, SuspiciousActivityReport, Transaction
from app.models.scoring import RiskAssessment, RiskClass


def _count_by(db: Session, column):
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {
        (k.value if hasattr(k, "value") else str(k)): n
        for k, n in rows
    }


def dashboard(db: Session) -> dict:
    """Tableau de bord agrégé LBC/FT."""
    return {
        "assessments_by_risk_class": _count_by(db, RiskAssessment.risk_class),
        "alerts_by_status": _count_by(db, Alert.status),
        "alerts_by_severity": _count_by(db, Alert.severity),
        "sars_by_status": _count_by(db, SuspiciousActivityReport.status),
        "open_alerts": db.execute(
            select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.OPEN)
        ).scalar_one(),
        "critical_alerts": db.execute(
            select(func.count()).select_from(Alert).where(Alert.severity == AlertSeverity.CRITICAL)
        ).scalar_one(),
        "transactions_total": db.execute(
            select(func.count()).select_from(Transaction)
        ).scalar_one(),
        "sars_pending": db.execute(
            select(func.count()).select_from(SuspiciousActivityReport).where(
                SuspiciousActivityReport.status != SARStatus.DECIDED
            )
        ).scalar_one(),
    }


def high_risk_subjects(db: Session, limit: int = 500) -> list[dict]:
    """
    Inventaire des sujets à risque élevé : dernière évaluation par sujet,
    classée HIGH ou CRITICAL.
    """
    rows = db.execute(
        select(RiskAssessment).order_by(RiskAssessment.created_at.desc())
    ).scalars().all()

    seen: set[str] = set()
    out: list[dict] = []
    for a in rows:
        key = a.subject_ref or str(a.id)
        if key in seen:
            continue
        seen.add(key)
        if a.risk_class in (RiskClass.HIGH, RiskClass.CRITICAL):
            out.append({
                "subject_ref": a.subject_ref,
                "subject_label": a.subject_label,
                "subject_type": a.subject_type.value,
                "risk_class": a.risk_class.value,
                "total_score": a.total_score,
                "scenarios": [t.get("code") for t in (a.triggered or [])],
                "assessed_at": a.created_at.isoformat() if a.created_at else None,
            })
        if len(out) >= limit:
            break
    return out


def sar_register(db: Session, limit: int = 500) -> list[dict]:
    """Registre des déclarations de soupçon."""
    rows = db.execute(
        select(SuspiciousActivityReport)
        .order_by(SuspiciousActivityReport.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": str(s.id),
            "subject_ref": s.subject_ref,
            "subject_label": s.subject_label,
            "reason": s.reason,
            "status": s.status.value,
            "decision": s.decision.value,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in rows
    ]
