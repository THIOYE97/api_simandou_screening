"""
Journal des connexions — écriture, détection de contexte inconnu, lecture.

Ce service répond à une question opérationnelle simple : « qui s'est connecté,
depuis où, et quand ». Il alimente la table `login_events` (cf. le modèle pour
les choix de conception) et met à jour `users.last_login_at`.

Principe directeur : **journaliser ne doit jamais empêcher de se connecter**.
Toutes les écritures passent par `record_safe`, qui avale ses erreurs après les
avoir tracées. Une panne du journal dégrade la traçabilité ; elle ne doit pas
fermer l'accès à la plateforme de conformité.

Détection du contexte inconnu : une connexion est signalée quand son adresse IP
ou son appareil n'a jamais été observé pour ce compte. La toute première
connexion d'un compte est donc signalée — c'est voulu : c'est l'événement qu'on
attend après avoir remis des accès à un tiers.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("simandou.login_audit")

EVENT_LOGIN_OK = "LOGIN_OK"
EVENT_LOGIN_FAILED = "LOGIN_FAILED"
EVENT_LOGOUT = "LOGOUT"
EVENT_REFRESH = "REFRESH"

EVENTS = (EVENT_LOGIN_OK, EVENT_LOGIN_FAILED, EVENT_LOGOUT, EVENT_REFRESH)

EVENT_LABELS = {
    EVENT_LOGIN_OK: "Connexion réussie",
    EVENT_LOGIN_FAILED: "Échec de connexion",
    EVENT_LOGOUT: "Déconnexion",
    EVENT_REFRESH: "Session prolongée",
}

REASON_LABELS = {
    "unknown_user": "adresse inconnue",
    "bad_password": "mot de passe incorrect",
    "disabled": "compte désactivé",
    "rotated": "renouvellement du jeton",
    "logout": "déconnexion",
    "logout_all": "déconnexion de tous les appareils",
}


# ── Écriture ──────────────────────────────────────────────────────────────────

def _known_context(
    db: Session,
    *,
    user_id: Optional[str],
    email: Optional[str],
    ip: Optional[str],
    user_agent: Optional[str],
) -> tuple[bool, bool, int]:
    """
    (adresse déjà vue, appareil déjà vu, nombre de connexions réussies passées).

    On se restreint aux connexions RÉUSSIES : un échec depuis une adresse
    inconnue ne doit pas « blanchir » cette adresse pour la connexion suivante.
    """
    if user_id:
        where = "user_id = CAST(:uid AS uuid)"
        params: dict[str, Any] = {"uid": str(user_id)}
    elif email:
        where = "lower(email) = lower(:email)"
        params = {"email": email}
    else:
        return (False, False, 0)

    params.update({"ip": ip, "ua": user_agent})

    row = db.execute(
        text(f"""
            SELECT
              COALESCE(bool_or(ip IS NOT DISTINCT FROM :ip), false)                 AS ip_seen,
              COALESCE(bool_or(user_agent IS NOT DISTINCT FROM :ua), false)         AS ua_seen,
              COUNT(*)::int                                                          AS previous
            FROM public.login_events
            WHERE event = '{EVENT_LOGIN_OK}' AND {where}
        """),
        params,
    ).mappings().first()

    if not row:
        return (False, False, 0)
    return (bool(row["ip_seen"]), bool(row["ua_seen"]), int(row["previous"]))


def record(
    db: Session,
    *,
    event: str,
    email: Optional[str] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    reason: Optional[str] = None,
    detect_new_context: bool = False,
) -> dict:
    """Écrit un événement et le renvoie. Peut lever — préférer `record_safe`."""
    known_ip = known_device = True
    previous = 1

    if detect_new_context:
        known_ip, known_device, previous = _known_context(
            db, user_id=user_id, email=email, ip=ip, user_agent=user_agent
        )

    is_new_context = detect_new_context and (not known_ip or not known_device)

    row = db.execute(
        text("""
            INSERT INTO public.login_events
                (event, reason, user_id, email, tenant_id, ip, user_agent, is_new_context)
            VALUES
                (:event, :reason, CAST(:uid AS uuid), :email, CAST(:tid AS uuid),
                 :ip, :ua, :new_ctx)
            RETURNING id::text AS id, created_at
        """),
        {
            "event": event,
            "reason": reason,
            "uid": str(user_id) if user_id else None,
            "email": (email or "")[:320] or None,
            "tid": str(tenant_id) if tenant_id else None,
            "ip": (ip or "")[:64] or None,
            "ua": (user_agent or "")[:1024] or None,
            "new_ctx": is_new_context,
        },
    ).mappings().first()

    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "event": event,
        "reason": reason,
        "user_id": str(user_id) if user_id else None,
        "email": email,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "ip": ip,
        "user_agent": user_agent,
        "is_new_context": is_new_context,
        "is_first_login": detect_new_context and previous == 0,
        "new_ip": detect_new_context and not known_ip,
        "new_device": detect_new_context and not known_device,
    }


def record_safe(db: Session, **kwargs) -> Optional[dict]:
    """
    `record` + commit, sans jamais propager d'erreur.

    Appelée depuis les routes d'authentification : un journal indisponible ne
    doit pas transformer une connexion valide en erreur 500.
    """
    try:
        out = record(db, **kwargs)
        db.commit()
        return out
    except Exception:
        logger.exception("login_event_write_failed", extra={"event": kwargs.get("event")})
        try:
            db.rollback()
        except Exception:
            pass
        return None


def touch_last_login(db: Session, *, user_id: str, ip: Optional[str]) -> None:
    """Met à jour la dernière connexion réussie du compte. Ne lève jamais."""
    try:
        db.execute(
            text("""
                UPDATE public.users
                   SET last_login_at = now(),
                       last_login_ip = :ip
                 WHERE id = CAST(:uid AS uuid)
            """),
            {"uid": str(user_id), "ip": (ip or "")[:64] or None},
        )
        db.commit()
    except Exception:
        logger.exception("last_login_update_failed", extra={"user_id": str(user_id)})
        try:
            db.rollback()
        except Exception:
            pass


# ── Alerte par courriel ───────────────────────────────────────────────────────

def _alert_enabled() -> bool:
    return (os.getenv("LOGIN_ALERT_ENABLED", "true") or "").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _alert_recipients() -> Optional[str]:
    """Destinataires dédiés, sinon la boîte Conformité déjà configurée."""
    return os.getenv("LOGIN_ALERT_TO_EMAIL") or os.getenv("BREVO_TO_EMAIL")


def _motif(event: dict) -> str:
    if event.get("is_first_login"):
        return "première connexion de ce compte"
    bouts = []
    if event.get("new_ip"):
        bouts.append("adresse IP jamais vue")
    if event.get("new_device"):
        bouts.append("appareil ou navigateur jamais vu")
    return " et ".join(bouts) or "contexte inhabituel"


def build_alert_email(event: dict, *, full_name: Optional[str] = None) -> tuple[str, str]:
    """(sujet, corps HTML) de l'alerte de connexion inhabituelle."""
    qui = full_name or event.get("email") or "compte inconnu"
    quand = event.get("created_at")
    quand_txt = quand.strftime("%d/%m/%Y à %H:%M UTC") if hasattr(quand, "strftime") else str(quand)

    sujet = f"[LBC/FT] Nouvelle connexion — {qui}"
    html = f"""
    <div style="font-family:system-ui,Segoe UI,Arial,sans-serif;font-size:14px;color:#1c2430">
      <h2 style="margin:0 0 4px;font-size:17px">Connexion depuis un contexte inconnu</h2>
      <p style="margin:0 0 16px;color:#5b6673">Motif : {_motif(event)}.</p>
      <table cellpadding="6" style="border-collapse:collapse;font-size:14px">
        <tr><td style="color:#5b6673">Compte</td><td><strong>{qui}</strong></td></tr>
        <tr><td style="color:#5b6673">Adresse électronique</td><td>{event.get('email') or '—'}</td></tr>
        <tr><td style="color:#5b6673">Date</td><td>{quand_txt}</td></tr>
        <tr><td style="color:#5b6673">Adresse IP</td><td>{event.get('ip') or '—'}</td></tr>
        <tr><td style="color:#5b6673">Appareil</td><td>{(event.get('user_agent') or '—')[:200]}</td></tr>
      </table>
      <p style="margin:18px 0 0;color:#5b6673">
        Le détail est consultable dans <em>Journal de connexions</em> (espace administrateur).
        Si cette connexion n'est pas attendue, révoquez les sessions du compte
        et changez son mot de passe.
      </p>
    </div>
    """
    return sujet, html


def notify_new_context(event: dict, *, full_name: Optional[str] = None) -> None:
    """
    Envoie l'alerte de connexion inhabituelle. Ne lève jamais.

    Appelée en tâche de fond : l'ouverture d'une session SMTP prend parfois
    plusieurs secondes, ce qui ralentirait la connexion de l'utilisateur.
    """
    if not event or not event.get("is_new_context"):
        return
    if not _alert_enabled():
        return

    destinataires = _alert_recipients()
    if not destinataires:
        logger.info("login_alert_skipped_no_recipient")
        return

    try:
        from app.services import list_notifier

        sujet, html = build_alert_email(event, full_name=full_name)
        list_notifier.send_html_email(sujet, html, recipients=destinataires)
    except Exception:
        logger.exception("login_alert_failed")


# ── Lecture (console de sécurité) ─────────────────────────────────────────────

def list_events(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    event: Optional[str] = None,
    email: Optional[str] = None,
    days: Optional[int] = None,
    only_new_context: bool = False,
) -> dict:
    """Journal paginé, du plus récent au plus ancien."""
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": max(1, min(limit, 200)), "offset": max(0, offset)}

    if event:
        clauses.append("e.event = :event")
        params["event"] = event
    if email:
        clauses.append("e.email ILIKE :email")
        params["email"] = f"%{email.strip()}%"
    if days:
        clauses.append("e.created_at >= now() - make_interval(days => :days)")
        params["days"] = int(days)
    if only_new_context:
        clauses.append("e.is_new_context")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    total = db.execute(
        text(f"SELECT COUNT(*)::int FROM public.login_events e {where}"), params
    ).scalar() or 0

    rows = db.execute(
        text(f"""
            SELECT
              e.id::text                AS id,
              e.event,
              e.reason,
              e.email,
              e.user_id::text           AS user_id,
              e.tenant_id::text         AS tenant_id,
              e.ip,
              e.user_agent,
              e.is_new_context,
              e.created_at,
              u.full_name,
              t.name                    AS tenant_name
            FROM public.login_events e
            LEFT JOIN public.users u   ON u.id = e.user_id
            LEFT JOIN public.tenants t ON t.id = e.tenant_id
            {where}
            ORDER BY e.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    return {
        "items": [_serialize_event(r) for r in rows],
        "total": total,
        "limit": params["limit"],
        "offset": params["offset"],
    }


def _serialize_event(r) -> dict:
    d = dict(r)
    d["event_label"] = EVENT_LABELS.get(d.get("event"), d.get("event"))
    d["reason_label"] = REASON_LABELS.get(d.get("reason")) if d.get("reason") else None
    created = d.get("created_at")
    d["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
    return d


def summary(db: Session) -> dict:
    """Chiffres de tête de la console de sécurité (fenêtres 24 h et 7 jours)."""
    row = db.execute(
        text(f"""
            SELECT
              COUNT(*) FILTER (
                WHERE event = '{EVENT_LOGIN_OK}' AND created_at >= now() - interval '24 hours'
              )::int AS logins_24h,
              COUNT(*) FILTER (
                WHERE event = '{EVENT_LOGIN_OK}' AND created_at >= now() - interval '7 days'
              )::int AS logins_7d,
              COUNT(DISTINCT user_id) FILTER (
                WHERE event = '{EVENT_LOGIN_OK}' AND created_at >= now() - interval '7 days'
              )::int AS users_7d,
              COUNT(*) FILTER (
                WHERE event = '{EVENT_LOGIN_FAILED}' AND created_at >= now() - interval '24 hours'
              )::int AS failures_24h,
              COUNT(*) FILTER (
                WHERE is_new_context AND created_at >= now() - interval '7 days'
              )::int AS new_contexts_7d
            FROM public.login_events
        """)
    ).mappings().first()

    derniere = db.execute(
        text(f"""
            SELECT created_at, email, ip
            FROM public.login_events
            WHERE event = '{EVENT_LOGIN_OK}'
            ORDER BY created_at DESC
            LIMIT 1
        """)
    ).mappings().first()

    out = dict(row or {})
    if derniere:
        out["last_login"] = {
            "created_at": derniere["created_at"].isoformat(),
            "email": derniere["email"],
            "ip": derniere["ip"],
        }
    else:
        out["last_login"] = None
    return out


def active_sessions(db: Session, *, limit: int = 100) -> list[dict]:
    """
    Sessions ouvertes = jetons de rafraîchissement ni révoqués ni expirés.

    C'est la réponse à « qui est connecté en ce moment », par opposition au
    journal qui répond à « qui s'est connecté ».
    """
    rows = db.execute(
        text("""
            SELECT
              r.id::text        AS id,
              r.user_id::text   AS user_id,
              u.email,
              u.full_name,
              t.name            AS tenant_name,
              r.issued_at,
              r.expires_at,
              r.client_ip       AS ip,
              r.user_agent
            FROM public.refresh_tokens r
            LEFT JOIN public.users u   ON u.id = r.user_id
            LEFT JOIN public.tenants t ON t.id = r.tenant_id
            WHERE r.revoked_at IS NULL
              AND r.expires_at > now()
            ORDER BY r.issued_at DESC
            LIMIT :limit
        """),
        {"limit": max(1, min(limit, 500))},
    ).mappings().all()

    out = []
    for r in rows:
        d = dict(r)
        for champ in ("issued_at", "expires_at"):
            v = d.get(champ)
            d[champ] = v.isoformat() if hasattr(v, "isoformat") else v
        out.append(d)
    return out


def accounts(db: Session, *, limit: int = 200) -> list[dict]:
    """Inventaire des comptes avec leur dernière connexion — comptes dormants inclus."""
    rows = db.execute(
        text("""
            SELECT
              u.id::text     AS id,
              u.email,
              u.full_name,
              u.status,
              u.is_active,
              t.name         AS tenant_name,
              u.created_at,
              u.last_login_at,
              u.last_login_ip
            FROM public.users u
            LEFT JOIN public.tenants t ON t.id = u.tenant_id
            ORDER BY u.last_login_at DESC NULLS LAST, u.created_at DESC
            LIMIT :limit
        """),
        {"limit": max(1, min(limit, 500))},
    ).mappings().all()

    out = []
    for r in rows:
        d = dict(r)
        for champ in ("created_at", "last_login_at"):
            v = d.get(champ)
            d[champ] = v.isoformat() if hasattr(v, "isoformat") else v
        out.append(d)
    return out
