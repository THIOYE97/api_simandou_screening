"""
Liste noire et interdits bancaires de la BCRG — endpoints REST.

TDR §VII, sous-module Liste noire. Le rapprochement n'a rien de spécifique :
ces personnes rejoignent l'index de filtrage commun. Ce module ne porte que
l'alimentation et le suivi de la liste.
"""
from fastapi import (APIRouter, Depends, File, HTTPException, Query, Response,
                     UploadFile)

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.services import blacklist_service as svc

router = APIRouter(
    prefix="/blacklist",
    tags=["blacklist"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/state")
def etat(db=Depends(get_db)):
    return svc.etat(db)


@router.get("/records")
def lister(limit: int = Query(500, ge=1, le=2000), db=Depends(get_db)):
    return {"records": svc.lister(db, limit=limit), "motifs": list(svc.MOTIFS_COURANTS)}


@router.get("/template.csv", dependencies=[Depends(require("lists:manage"))])
def modele():
    return Response(
        content=svc.modele_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="modele-liste-noire-bcrg.csv"'},
    )


@router.post("/import", dependencies=[Depends(require("lists:manage"))])
async def importer(
    fichier: UploadFile = File(...),
    dry_run: bool = Query(False),
    db=Depends(get_db),
):
    """
    Reverse la liste de la BCRG.

    Le fichier fait autorité : une référence absente vaut LEVÉE d'interdiction.
    C'est pourquoi la simulation existe et doit précéder tout reversement —
    un fichier incomplet lèverait des interdictions à tort, et rien dans le
    volume ne permet de distinguer une décision d'une erreur de manipulation.
    """
    if not (fichier.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Le fichier doit être au format CSV.")
    contenu = await fichier.read()
    if len(contenu) > 5 * 1024 * 1024:
        raise HTTPException(400, "Fichier trop volumineux (5 Mo maximum).")
    try:
        return svc.importer(db, contenu, dry_run=dry_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
