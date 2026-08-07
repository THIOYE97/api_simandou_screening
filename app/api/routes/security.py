# app/api/routes/security.py
"""
Console de sécurité — journal des connexions (Module 2).

Réservée au super-administrateur : ces écrans exposent des adresses IP, des
appareils et les comptes de TOUS les tenants. C'est aussi la raison pour
laquelle ils s'appuient sur `get_db_public` + le rôle d'authentification et non
sur la session RLS : la politique `tenant_isolation_users` filtre par tenant
sans échappatoire super-admin, donc une session RLS ne verrait qu'un tenant.
Le contournement est ici volontaire, borné à ces quatre lectures, et refermé
par un `RESET ROLE` systématique.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_public
from app.core.config import settings
from app.core.logging import get_logger
from app.services import login_audit_service

router = APIRouter(prefix="/security", tags=["security"])
logger = get_logger("simandou.security")


def _require_super_admin(user: dict) -> dict:
    if not user.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Réservé au super-administrateur")
    return user


def _open(db: Session) -> None:
    try:
        db.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))
    except Exception:
        logger.exception("security_set_role_failed")
        raise HTTPException(status_code=500, detail="Auth DB role misconfigured")


def _close(db: Session) -> None:
    try:
        db.execute(text("RESET ROLE"))
    except Exception:
        logger.exception("security_reset_role_failed")


@router.get("/login-events")
def login_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    event: Optional[str] = Query(None, description="LOGIN_OK | LOGIN_FAILED | LOGOUT | REFRESH"),
    email: Optional[str] = None,
    days: Optional[int] = Query(None, ge=1, le=365),
    only_new_context: bool = False,
    user=Depends(get_current_user),
    db: Session = Depends(get_db_public),
):
    """Journal des tentatives d'accès, du plus récent au plus ancien."""
    _require_super_admin(user)

    if event and event not in login_audit_service.EVENTS:
        raise HTTPException(status_code=422, detail=f"Événement inconnu : {event}")

    _open(db)
    try:
        return login_audit_service.list_events(
            db,
            limit=limit,
            offset=offset,
            event=event,
            email=email,
            days=days,
            only_new_context=only_new_context,
        )
    finally:
        _close(db)


@router.get("/login-summary")
def login_summary(
    user=Depends(get_current_user),
    db: Session = Depends(get_db_public),
):
    """Chiffres de tête : connexions 24 h / 7 j, comptes distincts, échecs, contextes inconnus."""
    _require_super_admin(user)
    _open(db)
    try:
        return login_audit_service.summary(db)
    finally:
        _close(db)


@router.get("/sessions")
def sessions(
    limit: int = Query(100, ge=1, le=500),
    user=Depends(get_current_user),
    db: Session = Depends(get_db_public),
):
    """Sessions ouvertes — qui est connecté en ce moment."""
    _require_super_admin(user)
    _open(db)
    try:
        return {"items": login_audit_service.active_sessions(db, limit=limit)}
    finally:
        _close(db)


@router.get("/accounts")
def accounts(
    limit: int = Query(200, ge=1, le=500),
    user=Depends(get_current_user),
    db: Session = Depends(get_db_public),
):
    """Comptes et dernière connexion — met en évidence les comptes jamais utilisés."""
    _require_super_admin(user)
    _open(db)
    try:
        return {"items": login_audit_service.accounts(db, limit=limit)}
    finally:
        _close(db)
