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
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db_public)):
    # Toujours repartir propre (évite fuite si connexion réutilisée)
    db.execute(text("RESET ROLE"))
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))

    # Bypass RLS uniquement pour lire public.users
    try:
        db.execute(text("SET ROLE auth_bypass_rls"))
    except Exception as e:
        print("[LOGIN] SET ROLE auth_bypass_rls failed:", repr(e))
        # Si le rôle n'existe pas / pas de droit, login échouera souvent avec RLS
        raise HTTPException(status_code=500, detail="Auth DB role misconfigured")

    info = db.execute(
        text(
            """
            select
                inet_server_addr() as server_addr,
                inet_server_port() as server_port,
                current_database() as db,
                current_user as usr,
                current_schema() as schema,
                current_setting('search_path') as search_path,
                current_setting('app.tenant_id', true) as tenant_ctx,
                current_setting('app.is_super_admin', true) as sa_ctx
        """
        )
    ).mappings().first()

    print("\n================ DB DEBUG ================")
    print("[SETTINGS] DATABASE_URL =", settings.DATABASE_URL)
    print("[LOGIN][DB INFO] =", dict(info))
    print("==========================================\n")

    # Pour login, on veut un contexte neutre
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))

    count_users = db.execute(text("select count(*) from public.users")).scalar()
    print("[LOGIN] users count in public.users =", count_users)

    u = get_user_by_email(db, payload.email)
    print("[LOGIN] email=", payload.email, "found=", bool(u))

    if not u:
        db.execute(text("RESET ROLE"))
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Debug: hash présent ?
    hashed = (u.get("password_hash") or "")
    print("[LOGIN] password_hash_len=", len(hashed))

    ok = verify_password(payload.password, hashed)
    print("[LOGIN] verify_password=", ok)

    if not ok:
        db.execute(text("RESET ROLE"))
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not u.get("is_active", True) or u.get("status") != "ACTIVE":
        db.execute(text("RESET ROLE"))
        raise HTTPException(status_code=403, detail="User disabled")

    token = create_access_token(
        {
            "sub": str(u["id"]),
            "tenant_id": str(u["tenant_id"]),
            "is_super_admin": bool(u.get("is_super_admin", False)),
        }
    )

    # très important : on rend la connexion propre au pool
    db.execute(text("RESET ROLE"))

    return TokenResponse(access_token=token)