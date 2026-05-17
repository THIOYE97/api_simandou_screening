# app/api/routes/auth.py
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_public
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import get_logger, user_id_ctx
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenPairResponse,
)
from app.services.auth_service import (
    consume_refresh_token,
    create_access_token,
    get_user_by_email,
    issue_refresh_token,
    revoke_all_user_tokens,
    revoke_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("simandou.auth")


def _reset_session(db: Session) -> None:
    db.execute(text("RESET ROLE"))
    db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    db.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip() or ip
    return ip, request.headers.get("user-agent")


def _access_token_for(user: dict) -> tuple[str, int]:
    token = create_access_token(
        {
            "sub": str(user["id"]),
            "tenant_id": str(user["tenant_id"]),
            "is_super_admin": bool(user.get("is_super_admin", False)),
        }
    )
    return token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


@router.post("/login", response_model=TokenPairResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
@limiter.limit(settings.RATE_LIMIT_LOGIN_PER_IP_DAY)
def login(
    request: Request,
    payload: Annotated[LoginRequest, Body()],
    db: Session = Depends(get_db_public),
):
    _reset_session(db)

    try:
        db.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))
    except Exception:
        logger.exception("SET ROLE auth_bypass failed")
        raise HTTPException(status_code=500, detail="Auth DB role misconfigured")

    try:
        u = get_user_by_email(db, payload.email)

        if not u:
            logger.info("login_failed", extra={"email": payload.email, "reason": "unknown_user"})
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not verify_password(payload.password, u.get("password_hash") or ""):
            logger.info(
                "login_failed",
                extra={"email": payload.email, "user_id": u.get("id"), "reason": "bad_password"},
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not u.get("is_active", True) or u.get("status") != "ACTIVE":
            logger.info(
                "login_failed",
                extra={"email": payload.email, "user_id": u.get("id"), "reason": "disabled"},
            )
            raise HTTPException(status_code=403, detail="User disabled")

        # Émet l'access token + persiste un refresh token
        access_token, expires_in = _access_token_for(u)

        ip, ua = _client_meta(request)
        refresh_token, refresh_expires_at = issue_refresh_token(
            db,
            user_id=str(u["id"]),
            tenant_id=str(u["tenant_id"]),
            client_ip=ip,
            user_agent=ua,
        )
        db.commit()

        user_id_ctx.set(str(u["id"]))
        logger.info(
            "login_success",
            extra={"user_id": str(u["id"]), "tenant_id": str(u["tenant_id"])},
        )
        return TokenPairResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            refresh_expires_at=refresh_expires_at,
        )

    finally:
        try:
            db.execute(text("RESET ROLE"))
        except Exception:
            logger.exception("RESET ROLE failed on login cleanup")


@router.post("/refresh", response_model=TokenPairResponse)
@limiter.limit("60/minute")
def refresh(
    request: Request,
    payload: Annotated[RefreshRequest, Body()],
    db: Session = Depends(get_db_public),
):
    """
    Échange un refresh token valide contre un nouveau couple (access, refresh).

    - Si REFRESH_TOKEN_ROTATION=True (défaut) : l'ancien refresh est révoqué,
      un nouveau est émis. C'est la pratique sûre (mitige le replay).
    - Sinon : on rééémet juste un access token, le refresh reste valide.
    """
    _reset_session(db)
    try:
        db.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))
    except Exception:
        logger.exception("SET ROLE auth_bypass failed (refresh)")
        raise HTTPException(status_code=500, detail="Auth DB role misconfigured")

    try:
        found = consume_refresh_token(db, token=payload.refresh_token)
        if not found:
            logger.info("refresh_failed", extra={"reason": "invalid_or_expired"})
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        # Recharge l'utilisateur (status peut avoir changé entre login et refresh)
        u = db.execute(
            text("""
                SELECT id::text AS id, email, full_name, is_active, status,
                       tenant_id::text AS tenant_id
                FROM public.users
                WHERE id = CAST(:uid AS uuid)
            """),
            {"uid": found["user_id"]},
        ).mappings().first()

        if not u or not u["is_active"] or u["status"] != "ACTIVE":
            # Coupe toutes les sessions de cet user — il a été désactivé
            revoke_all_user_tokens(db, user_id=found["user_id"], reason="user_disabled")
            db.commit()
            raise HTTPException(status_code=403, detail="User disabled")

        access_token, expires_in = _access_token_for(dict(u))

        if settings.REFRESH_TOKEN_ROTATION:
            revoke_refresh_token(db, token=payload.refresh_token, reason="rotated")
            ip, ua = _client_meta(request)
            new_refresh, new_expires_at = issue_refresh_token(
                db,
                user_id=str(u["id"]),
                tenant_id=str(u["tenant_id"]),
                client_ip=ip,
                user_agent=ua,
            )
            db.commit()
            logger.info("refresh_rotated", extra={"user_id": str(u["id"])})
            return TokenPairResponse(
                access_token=access_token,
                refresh_token=new_refresh,
                expires_in=expires_in,
                refresh_expires_at=new_expires_at,
            )

        # Pas de rotation : on renvoie le même refresh + nouveau access
        db.commit()
        logger.info("refresh_no_rotation", extra={"user_id": str(u["id"])})
        from datetime import datetime, timedelta, timezone
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        return TokenPairResponse(
            access_token=access_token,
            refresh_token=payload.refresh_token,
            expires_in=expires_in,
            refresh_expires_at=expires_at,
        )

    finally:
        try:
            db.execute(text("RESET ROLE"))
        except Exception:
            logger.exception("RESET ROLE failed on refresh cleanup")


@router.post("/logout", status_code=204)
def logout(
    payload: LogoutRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db_public),
):
    """
    Révoque :
      - Un refresh token précis (champ refresh_token), OU
      - Toutes les sessions de l'utilisateur (all_devices=True).

    Note : l'access token actuel reste valide jusqu'à son expiration
    (typiquement <30min) car il est stateless. C'est le compromis accepté
    de JWT — on minimise la fenêtre d'attaque en gardant ACCESS court.
    """
    _reset_session(db)
    try:
        db.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))
    except Exception:
        logger.exception("SET ROLE auth_bypass failed (logout)")
        raise HTTPException(status_code=500, detail="Auth DB role misconfigured")

    try:
        if payload.all_devices:
            n = revoke_all_user_tokens(db, user_id=str(user["id"]), reason="logout_all")
            db.commit()
            logger.info("logout_all", extra={"user_id": str(user["id"]), "revoked": n})
        elif payload.refresh_token:
            revoke_refresh_token(db, token=payload.refresh_token, reason="logout")
            db.commit()
            logger.info("logout_single", extra={"user_id": str(user["id"])})
        else:
            # Pas de refresh fourni, pas de all_devices → noop accepté
            logger.info("logout_noop", extra={"user_id": str(user["id"])})

    finally:
        try:
            db.execute(text("RESET ROLE"))
        except Exception:
            logger.exception("RESET ROLE failed on logout cleanup")
