from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_rls as get_db
from app.services.screening_runner import run_screening_request_mvp

router = APIRouter(prefix="/cascade", tags=["cascade"])

@router.post("/run/{request_id}")
def run_cascade(request_id: str, simulate_match: bool = False, db: Session = Depends(get_db)):
    try:
        risk, conf, action = run_screening_request_mvp(db=db, request_id=request_id, simulate_match=simulate_match)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "risk_level": risk, "confidence": conf, "recommended_action": action}
