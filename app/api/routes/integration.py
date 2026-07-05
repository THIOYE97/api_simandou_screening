"""
Passerelle d'interfaçage : endpoints REST.

Reçoit des flux exogènes (SWIFT MT103, T24 JSON), les normalise via les adapters
et les injecte dans le pipeline KYT (ingestion + analyse + alertes).
"""
from typing import Any

from fastapi import APIRouter, Body, Depends

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.schemas.kyt import IngestResult
from app.services import kyt_service
from app.services.integration import (
    ADAPTERS,
    map_rtgs_message,
    map_t24_transaction,
    parse_ach_batch,
    parse_mt103,
)

router = APIRouter(
    prefix="/integration",
    tags=["integration"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/adapters")
def list_adapters():
    """État des adapters d'interfaçage (T24 / SWIFT / ACP-ACH / RTGS)."""
    return {
        name: {"format": a["format"], "status": a["status"], "available": a["parser"] is not None}
        for name, a in ADAPTERS.items()
    }


def _ingest(db, user, data: dict) -> IngestResult:
    tenant_id = user.get("effective_tenant_id") or user.get("tenant_id")
    txn, assessment, alerts = kyt_service.ingest_transaction(db, data, tenant_id=tenant_id)
    return IngestResult(
        transaction=txn,
        risk_class=assessment.risk_class,
        total_score=assessment.total_score,
        triggered=assessment.triggered,
        alerts_created=len(alerts),
    )


@router.post("/swift/mt103", response_model=IngestResult, dependencies=[Depends(require("kyt:ingest"))])
def ingest_swift_mt103(
    message: str = Body(..., embed=True, description="Message SWIFT MT103 brut"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    return _ingest(db, user, parse_mt103(message))


@router.post("/t24/transaction", response_model=IngestResult, dependencies=[Depends(require("kyt:ingest"))])
def ingest_t24(
    record: dict[str, Any] = Body(..., description="Enregistrement de transaction T24"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    return _ingest(db, user, map_t24_transaction(record))


@router.post("/ach/batch", dependencies=[Depends(require("kyt:ingest"))])
def ingest_ach_batch(
    content: str = Body(..., embed=True, description="Lot de compensation ACP/ACH (délimité par ';')"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    entries = parse_ach_batch(content)
    results = [_ingest(db, user, e) for e in entries]
    return {
        "ingested": len(results),
        "alerts_created": sum(r.alerts_created for r in results),
        "results": results,
    }


@router.post("/rtgs/message", response_model=IngestResult, dependencies=[Depends(require("kyt:ingest"))])
def ingest_rtgs(
    message: dict[str, Any] = Body(..., description="Message RTGS (ISO 20022 pacs.008 simplifié)"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    return _ingest(db, user, map_rtgs_message(message))
