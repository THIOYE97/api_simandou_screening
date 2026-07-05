"""
Module 2 — RBAC : endpoints REST (habilitations paramétrables).

- /rbac/permissions           : catalogue des permissions
- /rbac/roles                 : définition des rôles (paramétrage)
- /rbac/me/permissions        : permissions effectives de l'appelant
- /rbac/users/{id}/roles      : affectation de rôles
- /rbac/seed                  : rôles par défaut
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.core.permissions import PERMISSIONS
from app.schemas.rbac import AssignRoleIn, RoleIn, RoleOut, RoleUpdate
from app.services import rbac_service as svc

router = APIRouter(
    prefix="/rbac",
    tags=["rbac"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/permissions")
def list_permissions():
    """Catalogue des permissions disponibles (référence pour composer les rôles)."""
    return PERMISSIONS


@router.get("/me/permissions")
def my_permissions(db=Depends(get_db), user=Depends(get_current_user)):
    perms = sorted(svc.get_user_permissions(db, user["id"], user.get("effective_tenant_id")))
    return {
        "user_id": user["id"],
        "is_super_admin": user.get("is_super_admin", False),
        "roles": svc.user_role_codes(db, user["id"], user.get("effective_tenant_id")),
        "permissions": ["*"] if user.get("is_super_admin") else perms,
    }


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db=Depends(get_db), user=Depends(get_current_user)):
    return svc.list_roles(db, tenant_id=user.get("effective_tenant_id"))


@router.post("/roles", response_model=RoleOut, dependencies=[Depends(require("roles:manage"))])
def create_role(payload: RoleIn, db=Depends(get_db), user=Depends(get_current_user)):
    data = payload.model_dump()
    data["tenant_id"] = user.get("effective_tenant_id")
    return svc.create_role(db, data)


@router.patch("/roles/{role_id}", response_model=RoleOut, dependencies=[Depends(require("roles:manage"))])
def update_role(role_id: UUID, payload: RoleUpdate, db=Depends(get_db)):
    obj = svc.update_role(db, role_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="Role not found")
    return obj


@router.post("/users/{user_id}/roles", dependencies=[Depends(require("roles:manage"))])
def assign_role(user_id: UUID, payload: AssignRoleIn, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.get("effective_tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    svc.assign_role(db, user_id, tenant_id, payload.role_code)
    return {"status": "ok", "user_id": str(user_id), "role": payload.role_code}


@router.delete("/users/{user_id}/roles/{role_code}", dependencies=[Depends(require("roles:manage"))])
def revoke_role(user_id: UUID, role_code: str, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.get("effective_tenant_id")
    svc.revoke_role(db, user_id, tenant_id, role_code)
    return {"status": "ok"}


@router.post("/seed", dependencies=[Depends(require("roles:manage"))])
def seed_roles(db=Depends(get_db)):
    return {"status": "ok", "created": svc.seed_roles(db)}
