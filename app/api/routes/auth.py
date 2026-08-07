# app/api/routes/auth.py
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
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
from app.services import login_audit_service
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
    background: BackgroundTasks,
    db: Session = Depends(get_db_public),
):
    _reset_session(db)

    try:
        db.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))
    except Exception:
        logger.exception("SET ROLE auth_bypass failed")
        raise HTTPException(status_code=500, detail="Auth DB role misconfigured")

    ip, ua = _client_meta(request)

    try:
        u = get_user_by_email(db, payload.email)

        if not u:
            logger.info("login_failed", extra={"email": payload.email, "reason": "unknown_user"})
            login_audit_service.record_safe(
                db,
                event=login_audit_service.EVENT_LOGIN_FAILED,
                email=payload.email,
                ip=ip,
                user_agent=ua,
                reason="unknown_user",
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not verify_password(payload.password, u.get("password_hash") or ""):
            logger.info(
                "login_failed",
                extra={"email": payload.email, "user_id": u.get("id"), "reason": "bad_password"},
            )
            login_audit_service.record_safe(
                db,
                event=login_audit_service.EVENT_LOGIN_FAILED,
                email=payload.email,
                user_id=str(u["id"]),
                tenant_id=str(u["tenant_id"]) if u.get("tenant_id") else None,
                ip=ip,
                user_agent=ua,
                reason="bad_password",
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not u.get("is_active", True) or u.get("status") != "ACTIVE":
            logger.info(
                "login_failed",
                extra={"email": payload.email, "user_id": u.get("id"), "reason": "disabled"},
            )
            login_audit_service.record_safe(
                db,
                event=login_audit_service.EVENT_LOGIN_FAILED,
                email=payload.email,
                user_id=str(u["id"]),
                tenant_id=str(u["tenant_id"]) if u.get("tenant_id") else None,
                ip=ip,
                user_agent=ua,
                reason="disabled",
            )
            raise HTTPException(status_code=403, detail="User disabled")

        # Émet l'access token + persiste un refresh token
        access_token, expires_in = _access_token_for(u)

        refresh_token, refresh_expires_at = issue_refresh_token(
            db,
            user_id=str(u["id"]),
            tenant_id=str(u["tenant_id"]),
            client_ip=ip,
            user_agent=ua,
        )
        db.commit()

        # Journal de connexion — APRÈS le commit de la session : une panne du
        # journal ne doit pas annuler une connexion déjà acquise.
        evenement = login_audit_service.record_safe(
            db,
            event=login_audit_service.EVENT_LOGIN_OK,
            email=u.get("email") or payload.email,
            user_id=str(u["id"]),
            tenant_id=str(u["tenant_id"]),
            ip=ip,
            user_agent=ua,
            detect_new_context=True,
        )
        login_audit_service.touch_last_login(db, user_id=str(u["id"]), ip=ip)

        # Adresse ou appareil jamais vus → alerte à la Conformité, hors du
        # chemin de réponse (une session SMTP prend plusieurs secondes).
        if evenement and evenement.get("is_new_context"):
            background.add_task(
                login_audit_service.notify_new_context,
                evenement,
                full_name=u.get("full_name"),
            )

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
                SELECT u.id::text AS id, u.email, u.full_name, u.is_active, u.status,
                       u.tenant_id::text AS tenant_id,
                       EXISTS (
                         SELECT 1 FROM public.user_roles ur
                         WHERE ur.user_id = u.id AND ur.role = 'SUPER_ADMIN'
                       ) AS is_super_admin
                FROM public.users u
                WHERE u.id = CAST(:uid AS uuid)
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
            login_audit_service.record_safe(
                db,
                event=login_audit_service.EVENT_REFRESH,
                email=u["email"],
                user_id=str(u["id"]),
                tenant_id=str(u["tenant_id"]),
                ip=ip,
                user_agent=ua,
                reason="rotated",
            )
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
    request: Request,
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

    ip, ua = _client_meta(request)

    def _trace(motif: str) -> None:
        login_audit_service.record_safe(
            db,
            event=login_audit_service.EVENT_LOGOUT,
            email=user.get("email"),
            user_id=str(user["id"]),
            tenant_id=str(user["tenant_id"]) if user.get("tenant_id") else None,
            ip=ip,
            user_agent=ua,
            reason=motif,
        )

    try:
        if payload.all_devices:
            n = revoke_all_user_tokens(db, user_id=str(user["id"]), reason="logout_all")
            db.commit()
            _trace("logout_all")
            logger.info("logout_all", extra={"user_id": str(user["id"]), "revoked": n})
        elif payload.refresh_token:
            revoke_refresh_token(db, token=payload.refresh_token, reason="logout")
            db.commit()
            _trace("logout")
            logger.info("logout_single", extra={"user_id": str(user["id"])})
        else:
            # Pas de refresh fourni, pas de all_devices → noop accepté
            logger.info("logout_noop", extra={"user_id": str(user["id"])})

    finally:
        try:
            db.execute(text("RESET ROLE"))
        except Exception:
            logger.exception("RESET ROLE failed on logout cleanup")
