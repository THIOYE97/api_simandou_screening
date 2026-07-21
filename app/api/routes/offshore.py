"""
Fuites offshore (ICIJ) — consultation à la demande.

Volontairement SÉPARÉ du filtrage automatique : une correspondance ici est une
piste d'enquête, jamais un motif de blocage. L'analyste interroge cette base
quand il instruit un dossier, elle n'intervient pas dans les contrôles courants.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.services import offshore_service as svc

router = APIRouter(prefix="/offshore", tags=["offshore"],
                   dependencies=[Depends(get_current_user)])


@router.get("/stats")
def offshore_stats(db=Depends(get_db)):
    """Volumétrie et attribution obligatoire à l'ICIJ."""
    return svc.stats(db)


@router.get("/search")
def offshore_search(
    q: str = Query(..., min_length=3),
    kind: Optional[str] = Query(default=None),
    limit: int = Query(30, ge=1, le=100),
    db=Depends(get_db),
):
    """
    Recherche par ressemblance dans les fuites.

    Le résultat porte toujours son avertissement : ces données s'arrêtent en
    2020 et figurer dans une structure offshore n'est pas un délit.
    """
    return {
        "results": svc.search(db, q, limit=limit, kind=kind),
        "attribution": svc.ICIJ_ATTRIBUTION,
        "caveat": ("Ces correspondances sont des pistes d'enquête, pas des motifs "
                   "de blocage : détenir une société offshore n'est pas illicite."),
    }


@router.post("/import", dependencies=[Depends(require("referentiel:write"))])
def offshore_import(
    kind: str = Query(..., description="OFFICER | ENTITY | INTERMEDIARY"),
    offset: int = Query(0, ge=0),
    limit: int = Query(5000, ge=1, le=50000),
    db=Depends(get_db),
):
    """
    Charge une tranche de l'archive ICIJ.

    L'import se fait par tranches car le corpus compte 1,6 million
    d'enregistrements : une seule requête n'y suffirait pas. L'archive est mise
    en cache sur disque, sinon chaque tranche retéléchargerait 70 Mo.
    """
    from app.services import list_adapters

    if kind.upper() not in ("OFFICER", "ENTITY", "INTERMEDIARY"):
        raise HTTPException(400, "Nature invalide.")
    try:
        path = list_adapters._download_to_file(svc.ICIJ_URL, cache_hours=72)
        out = svc.ingest(db, svc.parse_icij(path, kind.upper(), offset=offset, limit=limit))
    except Exception as e:
        raise HTTPException(502, f"Import impossible : {e}")
    return {"kind": kind.upper(), "offset": offset, **out,
            "next_offset": offset + out["read"],
            "finished": out["read"] < limit}
