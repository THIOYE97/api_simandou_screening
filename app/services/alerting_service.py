"""
Service métier — Module 6 Alerte.

- Paramétrage : CRUD des AlertRule + seed de règles par défaut.
- Détection : génération d'Alert à partir d'une RiskAssessment (scoring M7),
  en évaluant les règles actives.
- Administration : transitions de statut, affectation, résolution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alerting import (
    Alert,
    AlertRule,
    AlertSeverity,
    AlertSource,
    AlertStatus,
)
from app.models.scoring import RiskAssessment

# --- Évaluation d'une condition (même grammaire que le scoring) --------------

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


def _condition_met(condition: dict, ctx: dict) -> bool:
    field = condition.get("field")
    if field is None or field not in ctx:
        return False
    return _apply_op(ctx.get(field), condition.get("op", "=="), condition.get("value"))


# --- Détection : depuis une évaluation de risque ----------------------------

def _assessment_context(a: RiskAssessment) -> dict:
    severities = [t.get("severity") for t in (a.triggered or [])]
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    max_sev = max(severities, key=lambda s: order.get(s, -1)) if severities else None
    return {
        "risk_class": a.risk_class.value if hasattr(a.risk_class, "value") else a.risk_class,
        "total_score": a.total_score,
        "max_severity": max_sev,
        "scenario_codes": [t.get("code") for t in (a.triggered or [])],
    }


def generate_from_assessment(
    db: Session,
    assessment: RiskAssessment,
    source: AlertSource = AlertSource.SCORING,
) -> list[Alert]:
    """
    Applique les règles actives à une évaluation.

    `source` qualifie l'ORIGINE métier de l'alerte (SCREENING pour une
    vérification de personne/fournisseur, KYT pour une opération atypique) afin
    que la Conformité puisse les distinguer et les filtrer. Le filtrage des
    RÈGLES reste indépendant : elles sont toutes déclenchées par le scoring.
    """
    ctx = _assessment_context(assessment)
    rules = db.execute(
        select(AlertRule).where(
            AlertRule.active.is_(True), AlertRule.source == AlertSource.SCORING
        )
    ).scalars().all()

    created: list[Alert] = []
    for rule in rules:
        if _condition_met(rule.condition or {}, ctx):
            alert = Alert(
                tenant_id=assessment.tenant_id,
                source=source,
                severity=rule.severity,
                status=AlertStatus.ESCALATED if rule.auto_escalate else AlertStatus.OPEN,
                title=rule.name,
                rule_code=rule.code,
                subject_ref=assessment.subject_ref,
                subject_label=assessment.subject_label,
                risk_assessment_id=assessment.id,
                detail={"assessment": ctx, "rule": rule.code},
            )
            db.add(alert)
            created.append(alert)

    if created:
        db.commit()
        for a in created:
            db.refresh(a)
    return created


# --- Administration : cycle de vie ------------------------------------------

_ALLOWED_TRANSITIONS = {
    AlertStatus.OPEN: {AlertStatus.IN_REVIEW, AlertStatus.ESCALATED,
                       AlertStatus.CLOSED_TRUE_POSITIVE, AlertStatus.CLOSED_FALSE_POSITIVE},
    AlertStatus.IN_REVIEW: {AlertStatus.ESCALATED, AlertStatus.CLOSED_TRUE_POSITIVE,
                            AlertStatus.CLOSED_FALSE_POSITIVE},
    AlertStatus.ESCALATED: {AlertStatus.CLOSED_TRUE_POSITIVE, AlertStatus.CLOSED_FALSE_POSITIVE},
    AlertStatus.CLOSED_TRUE_POSITIVE: set(),
    AlertStatus.CLOSED_FALSE_POSITIVE: set(),
}


def _resolve_subject(db: Session, alert: Alert):
    """Retourne (subject_kind, subject_id, transaction|None) auditables."""
    from app.models.kyt import Transaction

    txn = None
    if alert.risk_assessment_id:
        txn = db.execute(
            select(Transaction).where(Transaction.risk_assessment_id == alert.risk_assessment_id)
        ).scalars().first()
    if txn:
        return "TRANSACTION", str(txn.id), txn
    screening = (alert.detail or {}).get("screening") if isinstance(alert.detail, dict) else None
    if screening and screening.get("request_id"):
        return "SCREENING", str(screening["request_id"]), None
    return "PERSON", alert.subject_ref, None


def _log_event(db, alert, action, to_status=None, decision=None, justification=None, user_id=None):
    from app.models.compliance import ComplianceEvent
    kind, sid, _ = _resolve_subject(db, alert)
    db.add(ComplianceEvent(
        tenant_id=alert.tenant_id, alert_id=alert.id,
        subject_kind=kind, subject_id=sid, subject_label=alert.subject_label,
        action=action, to_status=to_status, decision=decision,
        justification=justification, actor_id=user_id,
    ))


def transition_status(
    db: Session,
    alert_id: UUID,
    new_status: AlertStatus,
    user_id: Optional[UUID] = None,
    resolution: Optional[str] = None,
) -> Optional[Alert]:
    from fastapi import HTTPException

    alert = db.get(Alert, alert_id)
    if not alert:
        return None
    if new_status not in _ALLOWED_TRANSITIONS.get(alert.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Transition {alert.status.value} → {new_status.value} non autorisée",
        )

    closing = new_status in (AlertStatus.CLOSED_TRUE_POSITIVE, AlertStatus.CLOSED_FALSE_POSITIVE)
    if closing and (not resolution or len(resolution.strip()) < 4):
        raise HTTPException(status_code=400, detail="Justification obligatoire (min. 4 caractères).")

    kind, subject_id, txn = _resolve_subject(db, alert)
    alert.status = new_status

    action = "TAKE_CHARGE"
    decision = None

    if new_status == AlertStatus.IN_REVIEW:
        action = "TAKE_CHARGE"
        alert.assigned_to = user_id
    elif new_status == AlertStatus.ESCALATED:
        action = "ESCALATE"
    elif new_status == AlertStatus.CLOSED_TRUE_POSITIVE:
        action = "CONFIRM"
        decision = "BLOCKED"
        alert.resolution = resolution
        alert.resolved_by = user_id
        alert.resolved_at = datetime.now(timezone.utc)
        if txn is not None:
            txn.decision = "BLOCKED"
        _create_sar_from_alert(db, alert, resolution, user_id)
    elif new_status == AlertStatus.CLOSED_FALSE_POSITIVE:
        action = "DISMISS"
        decision = "AUTHORIZED"
        alert.resolution = resolution
        alert.resolved_by = user_id
        alert.resolved_at = datetime.now(timezone.utc)
        if txn is not None:
            txn.decision = "AUTHORIZED"

    _log_event(db, alert, action, to_status=new_status.value, decision=decision,
               justification=resolution, user_id=user_id)

    db.commit()
    db.refresh(alert)
    return alert


def _create_sar_from_alert(db: Session, alert: Alert, justification: Optional[str], user_id):
    """Crée un signalement de soupçon pré-rempli (une seule fois par alerte)."""
    from app.models.kyt import SARStatus, SuspiciousActivityReport

    existing = db.execute(
        select(SuspiciousActivityReport).where(SuspiciousActivityReport.related_alert_id == alert.id)
    ).scalars().first()
    if existing:
        return existing

    motifs = []
    if isinstance(alert.detail, dict):
        ass = alert.detail.get("assessment") or {}
        motifs = ass.get("scenario_codes") or []
    narrative = f"Soupçon confirmé sur alerte « {alert.title} ». "
    if justification:
        narrative += f"Justification : {justification}. "
    if motifs:
        narrative += f"Motifs : {', '.join(motifs)}."

    sar = SuspiciousActivityReport(
        tenant_id=alert.tenant_id,
        subject_ref=alert.subject_ref,
        subject_label=alert.subject_label,
        reason=alert.title,
        narrative=narrative,
        status=SARStatus.SUBMITTED,
        related_alert_id=alert.id,
        created_by=user_id,
    )
    db.add(sar)
    return sar


def assign(db: Session, alert_id: UUID, assignee: UUID) -> Optional[Alert]:
    alert = db.get(Alert, alert_id)
    if not alert:
        return None
    alert.assigned_to = assignee
    if alert.status == AlertStatus.OPEN:
        alert.status = AlertStatus.IN_REVIEW
    db.commit()
    db.refresh(alert)
    return alert


_ACTION_LABEL = {
    "TAKE_CHARGE": "Prise en charge",
    "ESCALATE": "Escaladée",
    "CONFIRM": "Soupçon confirmé",
    "DISMISS": "Alerte levée",
}


def _serialize_event(e) -> dict:
    return {
        "id": str(e.id),
        "action": e.action,
        "action_label": _ACTION_LABEL.get(e.action, e.action),
        "to_status": e.to_status,
        "decision": e.decision,
        "justification": e.justification,
        "subject_kind": e.subject_kind,
        "subject_id": e.subject_id,
        "subject_label": e.subject_label,
        "actor_id": str(e.actor_id) if e.actor_id else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def list_events(db: Session, subject_id: Optional[str] = None, alert_id: Optional[UUID] = None) -> list[dict]:
    from app.models.compliance import ComplianceEvent
    stmt = select(ComplianceEvent).order_by(ComplianceEvent.created_at.desc()).limit(100)
    if subject_id:
        stmt = stmt.where(ComplianceEvent.subject_id == subject_id)
    if alert_id:
        stmt = stmt.where(ComplianceEvent.alert_id == alert_id)
    return [_serialize_event(e) for e in db.execute(stmt).scalars().all()]


def get_alert_detail(db: Session, alert_id: UUID) -> Optional[dict]:
    """
    Dossier complet d'une alerte pour permettre l'intervention de la Conformité :
    l'alerte + l'évaluation de risque (contexte + scénarios déclenchés) + la
    transaction liée le cas échéant. Tout provient des MÊMES données (jointure
    par risk_assessment_id).
    """
    from app.models.kyt import Transaction  # import local (évite les cycles)

    alert = db.get(Alert, alert_id)
    if not alert:
        return None

    assessment = None
    transaction = None
    if alert.risk_assessment_id:
        a = db.get(RiskAssessment, alert.risk_assessment_id)
        if a:
            assessment = {
                "id": str(a.id),
                "subject_type": a.subject_type.value if hasattr(a.subject_type, "value") else a.subject_type,
                "subject_ref": a.subject_ref,
                "subject_label": a.subject_label,
                "total_score": a.total_score,
                "risk_class": a.risk_class.value if hasattr(a.risk_class, "value") else a.risk_class,
                "triggered": a.triggered or [],
                "context": a.context or {},
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
        t = db.execute(
            select(Transaction).where(Transaction.risk_assessment_id == alert.risk_assessment_id)
        ).scalars().first()
        if t:
            transaction = {
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
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }

    return {
        "id": str(alert.id),
        "source": alert.source.value if hasattr(alert.source, "value") else alert.source,
        "severity": alert.severity.value if hasattr(alert.severity, "value") else alert.severity,
        "status": alert.status.value if hasattr(alert.status, "value") else alert.status,
        "title": alert.title,
        "rule_code": alert.rule_code,
        "subject_ref": alert.subject_ref,
        "subject_label": alert.subject_label,
        "detail": alert.detail or {},
        "resolution": alert.resolution,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "assigned_to": str(alert.assigned_to) if alert.assigned_to else None,
        "subject_decision": (transaction or {}).get("decision") if transaction else None,
        "assessment": assessment,
        "transaction": transaction,
        "events": list_events(db, alert_id=alert.id),
    }


def list_alerts(
    db: Session,
    status: Optional[AlertStatus] = None,
    severity: Optional[AlertSeverity] = None,
    source: Optional[AlertSource] = None,
    limit: int = 50,
) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Alert.status == status)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if source:
        # SCREENING = vérification client/fournisseur ; KYT = opération atypique.
        stmt = stmt.where(Alert.source == source)
    return list(db.execute(stmt).scalars().all())


# --- Paramétrage : règles ----------------------------------------------------

def list_rules(db: Session) -> list[AlertRule]:
    return list(db.execute(select(AlertRule).order_by(AlertRule.code)).scalars().all())


def create_rule(db: Session, data: dict) -> AlertRule:
    obj = AlertRule(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


_DEFAULT_RULES = [
    {
        "code": "SCORING_HIGH_RISK",
        "name": "Client à risque élevé",
        "description": "Score de risque classé HIGH ou CRITICAL.",
        "source": AlertSource.SCORING,
        "severity": AlertSeverity.HIGH,
        "condition": {"field": "risk_class", "op": "in", "value": ["HIGH", "CRITICAL"]},
        "auto_escalate": False,
    },
    {
        "code": "SCORING_CRITICAL_SCENARIO",
        "name": "Scénario critique déclenché",
        "description": "Au moins un scénario de sévérité CRITICAL.",
        "source": AlertSource.SCORING,
        "severity": AlertSeverity.CRITICAL,
        "condition": {"field": "max_severity", "op": "==", "value": "CRITICAL"},
        "auto_escalate": True,
    },
]


def seed_rules(db: Session) -> int:
    existing = {r.code for r in list_rules(db)}
    n = 0
    for r in _DEFAULT_RULES:
        if r["code"] not in existing:
            db.add(AlertRule(**r))
            n += 1
    db.commit()
    return n
