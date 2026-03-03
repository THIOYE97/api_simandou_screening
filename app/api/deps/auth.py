# app/api/deps/auth.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_rls , get_db_public 
from app.services.auth_service import decode_access_token

bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# RLS context helpers
# ---------------------------------------------------------------------------

def set_super_admin_context(db: Session, is_super_admin: bool) -> None:
    """
    Stocke un flag en session PG, consommé par les RLS policies.
    ⚠️ is_local = false => survit aux commits dans la requête.
    """
    db.execute(
        text("SELECT set_config('app.is_super_admin', :v, false)"),
        {"v": "true" if is_super_admin else "false"},
    )


def set_tenant_context(db: Session, tenant_id: str | None) -> None:
    """
    Stocke le tenant_id en session PG (RLS).
    ⚠️ is_local = false => survit aux commits dans la requête.
    """
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(tenant_id or "")},
    )


def _resolve_effective_tenant_id(
    request: Request,
    token_tenant_id: Optional[str],
    is_super_admin: bool,
) -> Optional[str]:
    hdr = (request.headers.get("x-tenant-id") or "").strip()
    if is_super_admin and hdr:
        return hdr
    return token_tenant_id


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db_rls),
    db_public: Session = Depends(get_db_public),
):
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = creds.credentials

    # 1) Decode JWT
    try:
        payload = decode_access_token(token)
    except Exception as e:
        print("[AUTH] decode_access_token failed:", repr(e))
        raise HTTPException(status_code=401, detail="Invalid token")

    print("[AUTH] payload=", payload)

    user_id = payload.get("sub")
    token_tenant_id = payload.get("tenant_id")
    is_super_admin = bool(payload.get("is_super_admin") or False)

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload (sub missing)")

    # 2) Lire l'user via db_public (bypass RLS)
    try:
        db_public.execute(text("SET ROLE auth_bypass_rls"))
    except Exception as e:
        # si ton get_db_public est déjà en auth_bypass_rls c'est ok, sinon ça aide
        print("[AUTH] SET ROLE auth_bypass_rls failed:", repr(e))

    user = db_public.execute(
        text("""
            SELECT id, email, full_name, tenant_id, is_active, status
            FROM public.users
            WHERE id = :id
        """),
        {"id": user_id},
    ).mappings().first()

    print("[AUTH] user lookup found=", bool(user))

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user["is_active"] or user["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="User disabled")

    # 3) Tenant effectif
    effective_tenant_id = _resolve_effective_tenant_id(request, token_tenant_id, is_super_admin)

    # pour non-super-admin on impose le tenant réel du user
    if not is_super_admin:
        effective_tenant_id = str(user["tenant_id"])

    if not effective_tenant_id:
        raise HTTPException(status_code=401, detail="Invalid token payload (tenant_id missing)")

    print("[AUTH] effective_tenant_id=", effective_tenant_id, "is_super_admin=", is_super_admin)

    # 4) Appliquer le contexte RLS sur la session db (get_db_rls)
    set_super_admin_context(db, is_super_admin)
    set_tenant_context(db, effective_tenant_id)

    out = dict(user)
    out["is_super_admin"] = is_super_admin
    out["effective_tenant_id"] = effective_tenant_id
    out["tenant_id"] = effective_tenant_id

    return out

# ---------------------------------------------------------------------------
# Optional guard: tenant active
# ---------------------------------------------------------------------------

def assert_user_and_tenant_active(db: Session, user: Any):
    status_val = user["status"] if isinstance(user, dict) else getattr(user, "status", None)
    if status_val != "ACTIVE":
        raise HTTPException(status_code=403, detail="User disabled or not active")

    tenant_id = user["tenant_id"] if isinstance(user, dict) else getattr(user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant not found")

    tenant = db.execute(
        text(
            """
            SELECT id, status, active_until
            FROM tenants
            WHERE id = :tid
            """
        ),
        {"tid": str(tenant_id)},
    ).mappings().first()

    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant not found")

    if tenant["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="Tenant not active")

    if tenant["active_until"]:
        now = datetime.now(timezone.utc)
        if tenant["active_until"] < now:
            raise HTTPException(status_code=403, detail="Tenant subscription expired")
