# app/core/db.py
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # important
)


def _reset_context(db: Session) -> None:
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    db.execute(text("RESET ROLE"))


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


def get_db():
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