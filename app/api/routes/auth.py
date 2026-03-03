# app/api/routes/auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api.deps.db import get_db_public
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth_service import (
    get_user_by_email,
    verify_password,
    create_access_token,
)
from app.core.config import settings  # pour afficher DATABASE_URL

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db_public)):
    db.execute(text("SET ROLE auth_bypass_rls"))  # ✅ bypass RLS pour auth
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))


    # 🔎 DEBUG: infos DB réellement utilisée
    info = db.execute(text("""
        select
            inet_server_addr() as server_addr,
            inet_server_port() as server_port,
            current_database() as db,
            current_user as usr,
            current_schema() as schema,
            current_setting('search_path') as search_path
    """)).mappings().first()

    print("\n================ DB DEBUG ================")
    print("[SETTINGS] DATABASE_URL =", settings.DATABASE_URL)
    print("[LOGIN][DB INFO] =", dict(info))
    print("==========================================\n")

    # ✅ force un contexte lisible pour la phase login
    db.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))

    # 🔎 DEBUG: vérifier si la table contient des users
    count_users = db.execute(text("select count(*) from public.users")).scalar()
    print("[LOGIN] users count in public.users =", count_users)

    u = get_user_by_email(db, payload.email)
    print("[LOGIN] email=", payload.email, "found=", bool(u))

    if not u:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    hashed = (u.get("password_hash") or "")
    ok = verify_password(payload.password, hashed)
    print("[LOGIN] verify_password=", ok)

    if not ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not u.get("is_active", True) or u.get("status") != "ACTIVE":
        raise HTTPException(status_code=403, detail="User disabled")

    token = create_access_token({
        "sub": str(u["id"]),
        "tenant_id": str(u["tenant_id"]),
        "is_super_admin": bool(u.get("is_super_admin", False)),
    })

    return TokenResponse(access_token=token)
