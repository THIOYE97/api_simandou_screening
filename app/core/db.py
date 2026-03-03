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


def set_tenant_context(db: Session, tenant_id: str):
    db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})

def set_super_admin_context(db: Session, is_super_admin: bool):
    db.execute(
        text("SELECT set_config('app.is_super_admin', :v, true)"),
        {"v": "true" if is_super_admin else "false"},
    )

def get_db():
    db = SessionLocal()
    try:
        # LOCAL transaction scope
        db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        db.execute(text("SELECT set_config('app.is_super_admin', 'false', true)"))
        yield db
    finally:
        db.close()
