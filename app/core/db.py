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

# Optionnel (prod-safe) : rôle utilisé pour bypass auth (sans BYPASSRLS)
AUTH_BYPASS_ROLE = os.getenv("AUTH_BYPASS_ROLE", "").strip()


def reset_context(db: Session) -> None:
    # false => session-level (survit aux commits)
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    db.execute(text("RESET ROLE"))


def try_set_role(db: Session, role: str) -> bool:
    """
    Tente SET ROLE <role>. Retourne True si ok, False sinon.
    Ne lève pas d'exception (important en prod).
    """
    role = (role or "").strip()
    if not role:
        return False
    try:
        db.execute(text(f"SET ROLE {role}"))
        return True
    except Exception as e:
        print(f"[DB] SET ROLE {role} failed:", repr(e))
        return False


def get_db_session() -> Session:
    db: Session = SessionLocal()
    reset_context(db)
    return db