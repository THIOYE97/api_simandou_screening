# app/core/db.py
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("simandou.db")


def _build_engine():
    """
    Pool tuning :
      - pool_size            : connexions persistantes du pool (default 20)
      - max_overflow         : connexions au-delà du pool, créées à la demande (30)
      - pool_recycle         : recycle les connexions plus vieilles que N s (1800 = 30min)
                               → évite les "server closed the connection unexpectedly"
                                 derrière LB / pgbouncer / Postgres serveurs gérés.
      - pool_pre_ping        : ping avant chaque check-out (détecte les sockets morts)
      - pool_timeout         : abandonne après N s d'attente d'une connexion (10s)
                               → préfère un 503 propre qu'un thread bloqué indéfiniment.

    Si on est derrière pgbouncer en transaction pooling, on doit désactiver les
    prepared statements côté psycopg3 (sinon erreurs "prepared statement already exists").
    """
    connect_args: dict = {}

    # psycopg3 : si pgbouncer transaction mode, désactiver les prepared statements
    if settings.DB_DISABLE_PREPARED_STATEMENTS:
        # psycopg3 expose prepare_threshold sur la connexion ;
        # côté SQLAlchemy 2.x on passe via connect_args
        connect_args["prepare_threshold"] = None

    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_pre_ping=True,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        connect_args=connect_args,
        # query echo: uniquement si LOG_LEVEL=DEBUG (sinon trop verbeux)
        echo=(settings.LOG_LEVEL == "DEBUG"),
    )

    logger.info(
        "db_engine_initialised",
        extra={
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
            "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
            "disable_prepared_statements": settings.DB_DISABLE_PREPARED_STATEMENTS,
        },
    )
    return engine


engine = _build_engine()

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
