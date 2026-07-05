"""
Dépendance FastAPI d'autorisation par permission (Module 2).

Usage :
    @router.post("/x", dependencies=[Depends(require("alerts:manage"))])

Règle : un super-admin passe toujours ; sinon on vérifie que l'utilisateur
possède la permission via ses rôles (RBAC paramétrable).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls
from app.core.permissions import ALL
from app.services import rbac_service


def require(permission: str):
    def _dep(user=Depends(get_current_user), db: Session = Depends(get_db_rls)):
        if user.get("is_super_admin"):
            return user
        perms = rbac_service.get_user_permissions(db, user["id"], user.get("effective_tenant_id"))
        if ALL in perms or permission in perms:
            return user
        raise HTTPException(status_code=403, detail=f"Permission requise : {permission}")
    return _dep
