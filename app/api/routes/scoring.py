"""
Module 7 — Scoring : endpoints REST.

Évaluation paramétrable du risque d'un sujet (client / transaction) et
consultation de l'historique des évaluations.
"""
from fastapi import APIRouter, Depends, Query

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.schemas.scoring import AssessmentOut, ScoreRequest
from app.services import alerting_service, scoring_service as svc

router = APIRouter(
    prefix="/scoring",
    tags=["scoring"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/evaluate", response_model=AssessmentOut, dependencies=[Depends(require("scoring:evaluate"))])
def evaluate(payload: ScoreRequest, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.get("effective_tenant_id") or user.get("tenant_id")
    assessment = svc.score_subject(
        db,
        subject_type=payload.subject_type,
        context=payload.context,
        subject_ref=payload.subject_ref,
        subject_label=payload.subject_label,
        created_by=user.get("id"),
        tenant_id=tenant_id,
        persist=True,
    )
    # Détection des occurrences (M6) : génère les alertes selon les règles actives.
    alerting_service.generate_from_assessment(db, assessment)
    return assessment


@router.get("/assessments", response_model=list[AssessmentOut])
def list_assessments(
    subject_ref: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db=Depends(get_db),
):
    return svc.list_assessments(db, subject_ref=subject_ref, limit=limit)
