# app/api/deps/db.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.db import SessionLocal, reset_context, try_set_bypass_role


def get_db_public():
    """
    Session sans tenant (login, healthcheck) => on tente bypass RLS.
    """
    db: Session = SessionLocal()
    try:
        reset_context(db)
        try_set_bypass_role(db)
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            reset_context(db)
        except Exception:
            pass
        db.close()


def get_db_rls():
    """
    Session RLS. Le tenant/super-admin sont appliqués dans get_current_user()
    et DOIVENT survivre aux commits => set_config(..., false).
    """
    db: Session = SessionLocal()
    try:
        reset_context(db)
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            reset_context(db)
        except Exception:
            pass
        db.close()