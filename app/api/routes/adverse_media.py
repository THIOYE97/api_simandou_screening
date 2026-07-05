"""
Adverse media : endpoints REST.

- /adverse-media/screen   : rapprocher un nom candidat de la base adverse media
- /adverse-media/records  : consulter / alimenter la base
"""
from fastapi import APIRouter, Depends

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


@router.get("/records", response_model=list[RecordOut])
def list_records(db=Depends(get_db)):
    return svc.list_records(db)


@router.post("/records", response_model=RecordOut, dependencies=[Depends(require("lists:manage"))])
def add_record(payload: RecordIn, db=Depends(get_db)):
    return svc.add_record(db, payload.model_dump())


@router.post("/seed", dependencies=[Depends(require("lists:manage"))])
def seed(db=Depends(get_db)):
    return {"status": "ok", "created": svc.seed_adverse_media(db)}
