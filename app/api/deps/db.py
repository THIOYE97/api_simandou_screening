# app/api/deps/db.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.db import get_db_session, reset_context


def get_db_public():
    """
    Session sans tenant (login, healthcheck).
    Ne force aucun rôle ici : le rôle auth bypass sera appliqué ponctuellement
    dans /auth/login et get_current_user si env définie.
    """
    db: Session = get_db_session()
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


def get_db_rls():
    """
    Session RLS.
    Le contexte RLS (tenant + superadmin) est appliqué dans get_current_user()
    via set_config(..., false).
    """
    db: Session = get_db_session()
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