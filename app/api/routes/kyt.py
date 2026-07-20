"""
Module 5 — KYT (comportements atypiques) + Déclaration de soupçon : endpoints REST.

- /kyt/transactions : ingestion + analyse (scoring + alertes) et consultation
- /kyt/sar          : déclaration de soupçon (workflow Cellule de Conformité)
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.models.kyt import SARStatus, SourceSystem
from app.schemas.kyt import (
    IngestResult,
    SARIn,
    SAROut,
    SARUpdate,
    TransactionOut,
)
from app.schemas.kyt import TransactionIn
from app.services import kyt_service as svc

router = APIRouter(
    prefix="/kyt",
    tags=["kyt"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/transactions", response_model=IngestResult, dependencies=[Depends(require("kyt:ingest"))])
def ingest_transaction(payload: TransactionIn, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.get("effective_tenant_id") or user.get("tenant_id")
    txn, assessment, alerts = svc.ingest_transaction(db, payload.model_dump(), tenant_id=tenant_id)
    return IngestResult(
        transaction=txn,
        risk_class=assessment.risk_class,
        total_score=assessment.total_score,
        triggered=assessment.triggered,
        alerts_created=len(alerts),
        parties=(assessment.context or {}).get("screened_parties", []),
    )


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    customer_ref: str | None = Query(default=None),
    source_system: SourceSystem | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db=Depends(get_db),
):
    return svc.list_transactions(db, customer_ref=customer_ref, source_system=source_system, limit=limit)


# --- Déclaration de soupçon --------------------------------------------------
@router.post("/sar", response_model=SAROut, dependencies=[Depends(require("sar:manage"))])
def create_sar(payload: SARIn, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.get("effective_tenant_id") or user.get("tenant_id")
    data = payload.model_dump()
    data["related_transaction_ids"] = [str(x) for x in data.get("related_transaction_ids", [])]
    if data.get("related_alert_id"):
        data["related_alert_id"] = data["related_alert_id"]
    return svc.create_sar(db, data, created_by=user.get("id"), tenant_id=tenant_id)


@router.get("/sar", response_model=list[SAROut])
def list_sars(
    status: SARStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db=Depends(get_db),
):
    return svc.list_sars(db, status=status, limit=limit)


@router.patch("/sar/{sar_id}", response_model=SAROut, dependencies=[Depends(require("sar:manage"))])
def update_sar(sar_id: UUID, payload: SARUpdate, db=Depends(get_db), user=Depends(get_current_user)):
    sar = svc.update_sar(
        db, sar_id,
        status=payload.status, decision=payload.decision,
        narrative=payload.narrative, reviewed_by=user.get("id"),
    )
    if not sar:
        raise HTTPException(status_code=404, detail="SAR not found")
    return sar


@router.get("/transactions/{txn_id}")
def transaction_detail(txn_id: UUID, db=Depends(get_db)):
    """Détail d'une opération + son évaluation de risque."""
    detail = svc.get_transaction_detail(db, txn_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return detail


@router.get("/transactions/{txn_id}/export.pdf")
def transaction_pdf(txn_id: UUID, db=Depends(get_db)):
    """Rapport PDF d'une opération surveillée (institutionnel BCRG)."""
    from fastapi import Response
    from app.services.pdf_report import build_transaction_pdf
    try:
        pdf = build_transaction_pdf(db, str(txn_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=operation-{str(txn_id)[:8]}.pdf"})
