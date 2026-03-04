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
    expire_on_commit=False,
)

RLS_BYPASS_ROLE = os.getenv("RLS_BYPASS_ROLE", "auth_bypass_rls").strip()


def reset_context(db: Session) -> None:
    # session-level (survit aux commits)
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    db.execute(text("RESET ROLE"))


def try_set_bypass_role(db: Session) -> None:
    """
    Pour les endpoints publics (login/health), on tente de bypass RLS.
    Ne doit JAMAIS casser si le rôle n'existe pas.
    """
    if not RLS_BYPASS_ROLE:
        return
    try:
        db.execute(text(f"SET ROLE {RLS_BYPASS_ROLE}"))
    except Exception as e:
        # en prod/render ça peut échouer => on log et on continue
        print("[DB] SET ROLE bypass failed:", repr(e))


def set_tenant_context(db: Session, tenant_id: str | None) -> None:
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(tenant_id or "")},
    )


def set_super_admin_context(db: Session, is_super_admin: bool) -> None:
    db.execute(
        text("SELECT set_config('app.is_super_admin', :v, false)"),
        {"v": "true" if is_super_admin else "false"},
    )