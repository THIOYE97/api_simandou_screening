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
def press_status(name: str = Query(min_length=3, max_length=200), db=Depends(get_db)):
    """
    État de la recherche de presse : sondé par l'écran, ne déclenche rien.
    """
    return svc.press_status(db, name)


@router.post("/press")
def press_start(name: str = Query(min_length=3, max_length=200), db=Depends(get_db)):
    """
    Déclenche la recherche et rend la main aussitôt.

    Mesuré : la source refuse environ deux requêtes sur trois et chaque
    tentative dure de 14 à 57 secondes. Attendre le résultat dans la requête
    HTTP figerait l'écran près d'une minute pour, souvent, un échec.
    """
    return svc.press_start(db, name)


@router.get("/records", response_model=list[RecordOut])
def list_records(db=Depends(get_db)):
    return svc.list_records(db)


@router.post("/records", response_model=RecordOut, dependencies=[Depends(require("lists:manage"))])
def add_record(payload: RecordIn, db=Depends(get_db)):
    return svc.add_record(db, payload.model_dump())


@router.post("/seed", dependencies=[Depends(require("lists:manage"))])
def seed(db=Depends(get_db)):
    return {"status": "ok", "created": svc.seed_adverse_media(db)}
