# app/api/deps/auth.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_rls, get_db_public
from app.core.config import settings
from app.core.db import set_super_admin_context, set_tenant_context
from app.core.logging import get_logger, tenant_id_ctx, user_id_ctx
from app.services.auth_service import decode_access_token

logger = get_logger("simandou.auth")
bearer = HTTPBearer(auto_error=False)


def _resolve_effective_tenant_id(
    request: Request,
    token_tenant_id: Optional[str],
    is_super_admin: bool,
) -> Optional[str]:
    hdr = (request.headers.get("x-tenant-id") or "").strip()
    if is_super_admin and hdr:
        return hdr
    return token_tenant_id


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db_rls),
    db_public: Session = Depends(get_db_public),
):
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    # 1) decode token
    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        logger.info("auth_token_invalid")
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    token_tenant_id = payload.get("tenant_id")
    is_super_admin = bool(payload.get("is_super_admin") or False)

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload (sub missing)")

    # 2) bypass RLS pour lire public.users (identique au login)
    try:
        db_public.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))
    except Exception:
        logger.exception("auth_set_role_failed")
        raise HTTPException(status_code=500, detail="Auth DB role misconfigured")

    user = db_public.execute(
        text("""
            SELECT
              id::text AS id,
              email,
              full_name,
              tenant_id::text AS tenant_id,
              is_active,
              status
            FROM public.users
            WHERE id = CAST(:id AS uuid)
        """),
        {"id": user_id},
    ).mappings().first()

    # ✅ Toujours reset le rôle après lecture
    try:
        db_public.execute(text("RESET ROLE"))
    except Exception:
        pass

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user["is_active"] or user["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="User disabled")

    # 3) tenant effectif
    effective_tenant_id = _resolve_effective_tenant_id(request, token_tenant_id, is_super_admin)

    # si pas super-admin: on force le tenant réel de la DB
    if not is_super_admin:
        effective_tenant_id = str(user["tenant_id"])

    if not effective_tenant_id:
        raise HTTPException(status_code=401, detail="Invalid token payload (tenant_id missing)")

    # 4) appliquer contexte RLS SUR db (la session "RLS")
    set_super_admin_context(db, is_super_admin)
    set_tenant_context(db, effective_tenant_id)

    # 5) propager dans les logs structurés
    user_id_ctx.set(str(user["id"]))
    tenant_id_ctx.set(str(effective_tenant_id))

    out = dict(user)
    out["is_super_admin"] = is_super_admin
    out["effective_tenant_id"] = effective_tenant_id
    out["tenant_id"] = effective_tenant_id
    return out


def assert_user_and_tenant_active(db: Session, user: Any):
    status_val = user["status"] if isinstance(user, dict) else getattr(user, "status", None)
    if status_val != "ACTIVE":
        raise HTTPException(status_code=403, detail="User disabled or not active")

    tenant_id = user["tenant_id"] if isinstance(user, dict) else getattr(user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant not found")

    tenant = db.execute(
        text("SELECT id, status, active_until FROM tenants WHERE id = :tid"),
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