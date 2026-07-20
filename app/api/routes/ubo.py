"""
Bénéficiaires effectifs — endpoints REST.

/ubo/declarations : registre des bénéficiaires effectifs par personne morale,
                    chaîne de détention, et filtrage contre les listes.
"""
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.services import ubo_service as svc

router = APIRouter(prefix="/ubo", tags=["ubo"], dependencies=[Depends(get_current_user)])

_WRITE = [Depends(require("ubo:write"))]


class MemberIn(BaseModel):
    full_name: str
    kind: str = "PERSON"                      # PERSON | ENTITY
    parent_id: Optional[UUID] = None          # maillon détenu (chaîne)
    nationality: Optional[str] = None
    country: Optional[str] = None
    date_of_birth: Optional[str] = None
    identifier: Optional[str] = None
    ownership_percent: Optional[float] = None
    control_nature: str = "CAPITAL"


class DeclarationIn(BaseModel):
    company_name: str
    company_ref: Optional[str] = None
    company_country: Optional[str] = None
    case_id: Optional[UUID] = None
    notes: Optional[str] = None
    members: list[MemberIn] = Field(default_factory=list)


def _decl_out(db, decl) -> dict[str, Any]:
    return {
        "id": str(decl.id),
        "company_name": decl.company_name,
        "company_ref": decl.company_ref,
        "company_country": decl.company_country,
        "case_id": str(decl.case_id) if decl.case_id else None,
        "notes": decl.notes,
        "last_screened_at": decl.last_screened_at.isoformat() if decl.last_screened_at else None,
        "created_at": decl.created_at.isoformat() if decl.created_at else None,
        "members": [svc.member_out(db, m) for m in svc.get_members(db, decl.id)],
    }


@router.get("/declarations")
def list_declarations(limit: int = Query(100, ge=1, le=200), db=Depends(get_db)):
    return [_decl_out(db, d) for d in svc.list_declarations(db, limit=limit)]


@router.post("/declarations", dependencies=_WRITE, status_code=201)
def create_declaration(payload: DeclarationIn, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.get("effective_tenant_id") or user.get("tenant_id")
    data = payload.model_dump()
    data["members"] = [
        {k: v for k, v in m.items() if v is not None or k in ("parent_id",)}
        for m in data.get("members", [])
    ]
    decl = svc.create_declaration(db, data, tenant_id=tenant_id, created_by=user.get("id"))
    return _decl_out(db, decl)


# NB : déclarée AVANT /declarations/{declaration_id}, sinon « lookup » serait
# interprété comme un identifiant et rejeté.
@router.get("/declarations/lookup")
def lookup_declaration(
    company_name: Optional[str] = Query(default=None),
    company_ref: Optional[str] = Query(default=None),
    db=Depends(get_db),
):
    """
    Rapproche une société de sa déclaration de bénéficiaires effectifs.

    Retourne `{"found": false}` plutôt qu'un 404 : l'absence de déclaration est
    une réponse métier normale — et c'est précisément ce qui rend une
    vérification de personne morale incomplète au regard des obligations LBC/FT.
    """
    decl = svc.find_declaration_for_company(db, company_name=company_name, company_ref=company_ref)
    if not decl:
        return {"found": False, "declaration": None}
    out = _decl_out(db, decl)
    owners = [m for m in out["members"] if m["is_beneficial_owner"]]
    return {
        "found": True,
        "declaration": out,
        "owners_count": len(owners),
        "flagged_count": len([m for m in owners if (m.get("matches") or [])]),
        "last_screened_at": out["last_screened_at"],
    }


@router.get("/declarations/{declaration_id}")
def get_declaration(declaration_id: UUID, db=Depends(get_db)):
    decl = svc.get_declaration(db, declaration_id)
    if not decl:
        raise HTTPException(404, "Déclaration introuvable")
    return _decl_out(db, decl)


@router.delete("/declarations/{declaration_id}", dependencies=_WRITE, status_code=204)
def delete_declaration(declaration_id: UUID, db=Depends(get_db)):
    if not svc.delete_declaration(db, declaration_id):
        raise HTTPException(404, "Déclaration introuvable")


@router.post("/declarations/{declaration_id}/members", dependencies=_WRITE, status_code=201)
def add_member(declaration_id: UUID, payload: MemberIn, db=Depends(get_db)):
    m = svc.add_member(db, declaration_id, payload.model_dump(exclude_none=True))
    if not m:
        raise HTTPException(404, "Déclaration introuvable")
    return svc.member_out(db, m)


@router.patch("/members/{member_id}", dependencies=_WRITE)
def update_member(member_id: UUID, payload: dict, db=Depends(get_db)):
    m = svc.update_member(db, member_id, payload)
    if not m:
        raise HTTPException(404, "Membre introuvable")
    return svc.member_out(db, m)


@router.delete("/members/{member_id}", dependencies=_WRITE, status_code=204)
def delete_member(member_id: UUID, db=Depends(get_db)):
    if not svc.delete_member(db, member_id):
        raise HTTPException(404, "Membre introuvable")


@router.post("/declarations/{declaration_id}/screen", dependencies=_WRITE)
def screen_declaration(declaration_id: UUID, db=Depends(get_db)):
    """Filtre tous les membres contre les listes et évalue le risque de la société."""
    out = svc.screen_declaration(db, declaration_id)
    if out is None:
        raise HTTPException(404, "Déclaration introuvable")
    return out
