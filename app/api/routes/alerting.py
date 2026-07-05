"""
Module 6 — Alerte : endpoints REST.

- /alertes                    : liste (Administration)
- /alertes/{id}/status        : transition de cycle de vie
- /alertes/{id}/assign        : affectation
- /alertes/rules              : paramétrage des règles
- /alertes/rules/seed         : règles par défaut
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.models.alerting import AlertSeverity, AlertStatus
from app.schemas.alerting import (
    AlertOut,
    AssignUpdate,
    RuleIn,
    RuleOut,
    StatusUpdate,
)
from app.services import alerting_service as svc

router = APIRouter(
    prefix="/alertes",
    tags=["alertes"],
    dependencies=[Depends(get_current_user)],
)


_MANAGE = [Depends(require("alerts:manage"))]


@router.get("", response_model=list[AlertOut])
def list_alerts(
    status: AlertStatus | None = Query(default=None),
    severity: AlertSeverity | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db=Depends(get_db),
):
    return svc.list_alerts(db, status=status, severity=severity, limit=limit)


@router.patch("/{alert_id}/status", response_model=AlertOut, dependencies=_MANAGE)
def update_status(alert_id: UUID, payload: StatusUpdate, db=Depends(get_db), user=Depends(get_current_user)):
    alert = svc.transition_status(
        db, alert_id, payload.status, user_id=user.get("id"), resolution=payload.resolution
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/{alert_id}/assign", response_model=AlertOut, dependencies=_MANAGE)
def assign_alert(alert_id: UUID, payload: AssignUpdate, db=Depends(get_db)):
    alert = svc.assign(db, alert_id, payload.assignee)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


# --- Paramétrage des règles -------------------------------------------------
@router.get("/rules", response_model=list[RuleOut])
def list_rules(db=Depends(get_db)):
    return svc.list_rules(db)


@router.post("/rules", response_model=RuleOut, dependencies=_MANAGE)
def create_rule(payload: RuleIn, db=Depends(get_db)):
    return svc.create_rule(db, payload.model_dump())


@router.post("/rules/seed", dependencies=_MANAGE)
def seed_rules(db=Depends(get_db)):
    return {"status": "ok", "created": svc.seed_rules(db)}


@router.get("/events")
def compliance_events(subject_id: str | None = None, db=Depends(get_db)):
    """Piste d'audit des décisions de Conformité pour un sujet (vérification/opération)."""
    return svc.list_events(db, subject_id=subject_id)


# ⚠️ à déclarer APRÈS /rules et /events pour ne pas masquer ces routes
@router.get("/{alert_id}")
def alert_detail(alert_id: UUID, db=Depends(get_db)):
    """Dossier complet d'une alerte (personne, motifs, opération liée) pour intervenir."""
    detail = svc.get_alert_detail(db, alert_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Alert not found")
    return detail
