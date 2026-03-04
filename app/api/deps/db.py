# app/api/deps/db.py
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.db import SessionLocal


def _reset_context(db: Session) -> None:
    # session-level (survit aux commits)
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    # CRITIQUE: évite la fuite de SET ROLE entre requêtes (pool)
    db.execute(text("RESET ROLE"))


def get_db_public():
    """
    Session sans tenant (login, healthcheck).
    Peut faire SET ROLE auth_bypass_rls ponctuellement,
    mais on RESET ROLE au début + fin pour ne rien "fuiter".
    """
    db: Session = SessionLocal()
    try:
        _reset_context(db)
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            _reset_context(db)
        except Exception:
            pass
        db.close()


def get_db_rls():
    """
    Session RLS.
    Le tenant/super-admin sont appliqués dans get_current_user()
    et DOIVENT survivre aux commits => set_config(..., false).
    """
    db: Session = SessionLocal()
    try:
        _reset_context(db)
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            _reset_context(db)
        except Exception:
            pass
        db.close()