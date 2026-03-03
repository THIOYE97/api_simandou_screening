# app/core/db.py
from __future__ import annotations

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # ✅ IMPORTANT
)

# Optionnel : si tu veux activer un role spécial en local uniquement
RLS_BYPASS_ROLE = os.getenv("RLS_BYPASS_ROLE", "").strip()


def _reset_context(db: Session) -> None:
    # false = session-level (survit aux commits)
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    # on revient au rôle normal si un SET ROLE a été fait avant
    db.execute(text("RESET ROLE"))


def maybe_set_role(db: Session) -> None:
    # Ne fait rien si l’ENV n’est pas défini (prod-safe)
    if not RLS_BYPASS_ROLE:
        return
    db.execute(text(f"SET ROLE {RLS_BYPASS_ROLE}"))


def set_tenant_context(db: Session, tenant_id: str) -> None:
    # false = session-level (survit aux commits)
    db.execute(text("SELECT set_config('app.tenant_id', :tid, false)"), {"tid": str(tenant_id)})


def set_super_admin_context(db: Session, is_super_admin: bool) -> None:
    db.execute(
        text("SELECT set_config('app.is_super_admin', :v, false)"),
        {"v": "true" if is_super_admin else "false"},
    )


def get_db():
    db: Session = SessionLocal()
    try:
        _reset_context(db)
        # Active seulement si tu mets RLS_BYPASS_ROLE dans l'env (ex: local)
        maybe_set_role(db)
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