"""
Module 8 — Reportings : endpoints REST (rapports d'inventaire, lecture seule).
"""
import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.services import reporting_service as svc

router = APIRouter(
    prefix="/reportings",
    tags=["reportings"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/dashboard")
def dashboard(db=Depends(get_db)):
    return svc.dashboard(db)


@router.get("/high-risk-subjects")
def high_risk_subjects(db=Depends(get_db)):
    return svc.high_risk_subjects(db)


@router.get("/high-risk-subjects.csv")
def high_risk_subjects_csv(db=Depends(get_db)):
    rows = svc.high_risk_subjects(db)

    def _iter():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["subject_ref", "subject_label", "subject_type",
                         "risk_class", "total_score", "scenarios", "assessed_at"])
        yield buf.getvalue()
        buf.seek(0), buf.truncate(0)
        for r in rows:
            writer.writerow([
                r["subject_ref"], r["subject_label"], r["subject_type"],
                r["risk_class"], r["total_score"], "|".join(r["scenarios"]),
                r["assessed_at"],
            ])
            yield buf.getvalue()
            buf.seek(0), buf.truncate(0)

    return StreamingResponse(
        _iter(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=high_risk_subjects.csv"},
    )


@router.get("/sar-register")
def sar_register(db=Depends(get_db)):
    return svc.sar_register(db)
