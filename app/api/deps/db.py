# app/api/deps/db.py
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.db import SessionLocal


def _reset_rls_context(db: Session) -> None:
    # IMPORTANT: is_local = false => valeur au niveau session
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))


def get_db_public():
    """
    Session sans tenant (login, healthcheck).
    """
    db: Session = SessionLocal()
    try:
        _reset_rls_context(db)
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            _reset_rls_context(db)
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
        # reset au début (safe)
        _reset_rls_context(db)
        yield db
    finally:
        # rollback (ferme une tx éventuellement ouverte)
        try:
            db.rollback()
        except Exception:
            pass
        # reset avant rendre la connexion au pool
        try:
            _reset_rls_context(db)
        except Exception:
            pass
        db.close()
