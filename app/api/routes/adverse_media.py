"""
Adverse media : endpoints REST.

- /adverse-media/screen   : rapprocher un nom candidat de la base adverse media
- /adverse-media/records  : consulter / alimenter la base
"""
from fastapi import APIRouter, Depends, Query

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.schemas.adverse_media import RecordIn, RecordOut, ScreenRequest
from app.services import adverse_media_service as svc

router = APIRouter(
    prefix="/adverse-media",
    tags=["adverse-media"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/screen")
def screen(payload: ScreenRequest, db=Depends(get_db)):
    matches = svc.screen_name(db, payload.name, threshold=payload.threshold)
    return {"name": payload.name, "hit": len(matches) > 0, "matches": matches}


@router.get("/press")
def press(name: str = Query(min_length=3, max_length=200),
          months: int = Query(24, ge=1, le=60)):
    """
    Pistes de presse pour une dénomination sociale (source libre GDELT).

    Consultée à la demande depuis l'écran, et non pendant la vérification : la
    source impose une requête toutes les 5 secondes et un appel systématique
    soumettrait chaque vérification à sa disponibilité.
    """
    return svc.search_press(name, months=months)


@router.get("/records", response_model=list[RecordOut])
def list_records(db=Depends(get_db)):
    return svc.list_records(db)


@router.post("/records", response_model=RecordOut, dependencies=[Depends(require("lists:manage"))])
def add_record(payload: RecordIn, db=Depends(get_db)):
    return svc.add_record(db, payload.model_dump())


@router.post("/seed", dependencies=[Depends(require("lists:manage"))])
def seed(db=Depends(get_db)):
    return {"status": "ok", "created": svc.seed_adverse_media(db)}
