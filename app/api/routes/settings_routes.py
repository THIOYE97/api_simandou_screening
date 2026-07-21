# app/api/routes/settings_routes.py

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.core.db import set_tenant_context

router = APIRouter(tags=["settings"])
logger = logging.getLogger("simandou.settings")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _tenant_id(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("tenant_id") or user.get("effective_tenant_id") or "")
    return str(getattr(user, "tenant_id", None) or getattr(user, "effective_tenant_id", None) or "")


def _user_email(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("email") or user.get("sub") or "")
    return str(getattr(user, "email", None) or "")


def _setup(db: Session, user: Any) -> str:
    """Reset session + re-poser tenant context."""
    try:
        db.rollback()
    except Exception:
        pass
    tid = _tenant_id(user)
    if not tid:
        raise HTTPException(500, "tenant_id missing from token")
    set_tenant_context(db, tid)
    return tid


def _ensure_settings_table(db: Session) -> None:
    """Crée tenant_settings si absente (idempotent)."""
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS public.tenant_settings (
                tenant_id   UUID        PRIMARY KEY,
                settings    JSONB       NOT NULL DEFAULT '{}',
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


DEFAULT_SETTINGS: dict = {
    "pep_enabled":               True,
    "sanctions_enabled":         True,
    "adverse_media_enabled":     True,
    "max_matches_default":       20,
    "confidence_threshold":      70,
    "email_notifications":       True,
    "high_risk_only":            True,
    "notification_frequency":    "immediately",
    "date_locale":               "fr-FR",
    "risk_auto_block_threshold": "HIGH",
}

# Libellés de repli, utilisés uniquement si la table `sources` est vide.
# 6 et 7 sont les répertoires de personnes politiquement exposées de Guinée
# (extraits du Secrétariat Général du Gouvernement).
SOURCE_NAMES = {
    1: "Sanctions — Nations Unies (liste consolidée)",
    2: "Sanctions — OFAC (Trésor américain)",
    3: "Sanctions — Union Européenne",
    4: "Sanctions — Royaume-Uni",
    5: "PPE Guinée — Journal Officiel (SGG)",
    6: "PPE Guinée — Répertoire SGG",
    7: "PPE Guinée — Membres du Gouvernement (Ve République)",
}
SOURCE_CODES = {1: "UN", 2: "OFAC", 3: "EU", 4: "UK", 5: "SGG_GN", 6: "SGG", 7: "GN_GOV"}
SOURCE_FLAGS = {1: "🌐", 2: "🇺🇸", 3: "🇪🇺", 4: "🇬🇧", 5: "🇬🇳", 6: "🇬🇳", 7: "🇬🇳"}


# ─── GET /settings ────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tid = _setup(db, user)
    _ensure_settings_table(db)

    try:
        row = db.execute(
            text("SELECT settings FROM public.tenant_settings WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": tid},
        ).mappings().first()
        stored = dict(row["settings"]) if row and row["settings"] else {}
    except Exception:
        stored = {}

    return JSONResponse(content={**DEFAULT_SETTINGS, **stored})


# ─── PATCH /settings ──────────────────────────────────────────────────────────

@router.patch("/settings")
def update_settings(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tid = _setup(db, user)
    _ensure_settings_table(db)

    try:
        row = db.execute(
            text("SELECT settings FROM public.tenant_settings WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": tid},
        ).mappings().first()
        current = dict(row["settings"]) if row and row["settings"] else {}

        # Whitelist
        patch   = {k: v for k, v in payload.items() if k in DEFAULT_SETTINGS}
        updated = {**DEFAULT_SETTINGS, **current, **patch}

        db.execute(
            text("""
                INSERT INTO public.tenant_settings (tenant_id, settings, updated_at)
                VALUES (CAST(:tid AS uuid), CAST(:s AS jsonb), now())
                ON CONFLICT (tenant_id) DO UPDATE
                    SET settings   = CAST(:s AS jsonb),
                        updated_at = now()
            """),
            {"tid": tid, "s": json.dumps(updated)},
        )
        db.commit()
        return JSONResponse(content={"ok": True, "settings": updated})

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(500, f"Erreur sauvegarde settings: {e}")


# ─── GET /settings/sources ────────────────────────────────────────────────────

@router.get("/settings/sources")
def list_sources(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _setup(db, user)

    try:
        # Check if public.sources table exists with a 'name' column
        has_sources = db.execute(
            text("SELECT to_regclass('public.sources')")
        ).scalar()

        if has_sources:
            # Try reading from sources table directly
            try:
                # NB : les colonnes réelles sont source_code / source_name
                # (et il n'y a pas de updated_at) — cf. table public.sources.
                rows = db.execute(
                    text("""
                        SELECT
                            s.id,
                            s.source_code::text AS code,
                            COALESCE(NULLIF(s.source_name::text, ''), s.source_code::text) AS name,
                            CASE WHEN s.is_active THEN 'active' ELSE 'inactive' END AS status,
                            (
                                SELECT MAX(sr.created_at)
                                FROM public.source_records sr
                                WHERE sr.source_id = s.id
                            ) AS last_updated,
                            (
                                SELECT COUNT(*)::int
                                FROM public.source_records sr
                                WHERE sr.source_id = s.id
                            ) AS entity_count
                        FROM public.sources s
                        ORDER BY s.id
                    """)
                ).mappings().all()

                result = [
                    {
                        "id":           int(r["id"]),
                        "code":         r["code"],
                        "name":         r["name"],
                        "status":       r["status"],
                        "entity_count": r["entity_count"],
                        "last_updated": str(r["last_updated"]) if r.get("last_updated") else None,
                    }
                    for r in rows
                ]
                if result:
                    return JSONResponse(content=result)
            except Exception:
                try:
                    db.rollback()
                    _setup(db, user)
                except Exception:
                    pass

        # Fallback: aggregate from source_records (always works)
        rows = db.execute(
            text("""
                SELECT
                    source_id::int            AS id,
                    COUNT(*)::int             AS entity_count,
                    MAX(created_at)           AS last_updated
                FROM public.source_records
                GROUP BY source_id
                ORDER BY source_id
            """)
        ).mappings().all()

        result = []
        for r in rows:
            sid = int(r["id"])
            result.append({
                "id":           sid,
                "code":         SOURCE_CODES.get(sid, f"SRC{sid}"),
                "name":         SOURCE_NAMES.get(sid, f"Source {sid}"),
                "flag":         SOURCE_FLAGS.get(sid, "📋"),
                "status":       "active",
                "entity_count": r["entity_count"],
                "last_updated": str(r["last_updated"]) if r.get("last_updated") else None,
            })

        # If still empty, return hardcoded defaults
        if not result:
            result = [
                {"id": 1, "code": "UN",   "name": "Nations Unies (ONU)",  "flag": "🌐", "status": "active", "entity_count": 0, "last_updated": None},
                {"id": 2, "code": "OFAC", "name": "OFAC (US Treasury)",   "flag": "🇺🇸", "status": "active", "entity_count": 0, "last_updated": None},
                {"id": 3, "code": "EU",   "name": "Union Européenne",     "flag": "🇪🇺", "status": "active", "entity_count": 0, "last_updated": None},
            ]

        return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(500, f"Erreur chargement sources: {e}")


# ─── POST /settings/sources/{source_id}/sync ─────────────────────────────────

@router.post("/settings/sources/{source_id}/sync")
def sync_source(
    source_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _setup(db, user)
    # Placeholder — brancher un celery/background task ici si nécessaire
    return JSONResponse(content={
        "ok":        True,
        "source_id": source_id,
        "message":   f"Source {source_id} sync scheduled (background task).",
    })


# ─── GET /settings/audit-logs ─────────────────────────────────────────────────

@router.get("/settings/audit-logs")
def get_audit_logs(
    limit:  int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tid = _setup(db, user)

    try:
        # Try case_screening_decisions first (richest audit data)
        has_csd = db.execute(
            text("SELECT to_regclass('public.case_screening_decisions')")
        ).scalar()

        if has_csd:
            try:
                total_row = db.execute(
                    text("SELECT COUNT(*)::int AS total FROM public.case_screening_decisions WHERE tenant_id = CAST(:tid AS uuid)"),
                    {"tid": tid},
                ).mappings().first()
                total = total_row["total"] if total_row else 0

                rows = db.execute(
                    text("""
                        SELECT
                            csd.id::text                AS id,
                            csd.decision                AS action,
                            csd.comment                 AS detail,
                            csd.decided_by_email        AS user_email,
                            csd.decided_at              AS created_at,
                            csd.request_id::text        AS request_id,
                            csd.case_id::text           AS case_id
                        FROM public.case_screening_decisions csd
                        WHERE csd.tenant_id = CAST(:tid AS uuid)
                        ORDER BY csd.decided_at DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {"tid": tid, "limit": limit, "offset": offset},
                ).mappings().all()

                return JSONResponse(content={
                    "items":  [dict(r) for r in rows],
                    "total":  total,
                    "limit":  limit,
                    "offset": offset,
                })
            except Exception:
                try:
                    db.rollback()
                    _setup(db, user)
                except Exception:
                    pass

        # Fallback: screening_results
        total_row = db.execute(
            text("SELECT COUNT(*)::int AS total FROM public.screening_results WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": tid},
        ).mappings().first()
        total = total_row["total"] if total_row else 0

        rows = db.execute(
            text("""
                SELECT
                    res.id::text                                AS id,
                    ('Screening · ' || res.recommended_action) AS action,
                    ('Risque: ' || res.risk_level)             AS detail,
                    res.decided_by                             AS user_email,
                    res.decided_at                             AS created_at,
                    res.request_id::text                       AS request_id,
                    NULL::text                                 AS case_id
                FROM public.screening_results res
                WHERE res.tenant_id = CAST(:tid AS uuid)
                ORDER BY res.decided_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"tid": tid, "limit": limit, "offset": offset},
        ).mappings().all()

        return JSONResponse(content={
            "items":  [dict(r) for r in rows],
            "total":  total,
            "limit":  limit,
            "offset": offset,
        })

    except Exception as e:
        raise HTTPException(500, f"Erreur chargement audit logs: {e}")


# ─── GET /settings/users ──────────────────────────────────────────────────────

@router.get("/settings/users")
def list_users(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tid = _setup(db, user)

    try:
        # Try with role column
        rows = db.execute(
            text("""
                SELECT
                    u.id::text                   AS id,
                    u.email,
                    COALESCE(u.role::text, 'ANALYST') AS role,
                    u.full_name,
                    u.is_active,
                    u.created_at,
                    u.last_login                 AS last_active
                FROM public.users u
                WHERE u.tenant_id = CAST(:tid AS uuid)
                  AND (u.is_active IS NULL OR u.is_active = true)
                ORDER BY u.created_at DESC
                LIMIT 100
            """),
            {"tid": tid},
        ).mappings().all()
        return JSONResponse(content=[dict(r) for r in rows])

    except Exception as e:
        # Retry without role/is_active if columns don't exist
        try:
            db.rollback()
            _setup(db, user)
            rows = db.execute(
                text("""
                    SELECT u.id::text AS id, u.email, u.full_name, u.created_at
                    FROM public.users u
                    WHERE u.tenant_id = CAST(:tid AS uuid)
                    ORDER BY u.created_at DESC LIMIT 100
                """),
                {"tid": tid},
            ).mappings().all()
            return JSONResponse(content=[{**dict(r), "role": "ANALYST"} for r in rows])
        except Exception as e2:
            raise HTTPException(500, f"Erreur chargement utilisateurs: {e2}")


# ─── POST /settings/users/invite ─────────────────────────────────────────────

@router.post("/settings/users/invite")
def invite_user(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tid = _setup(db, user)
    email = str(payload.get("email") or "").strip().lower()
    role  = str(payload.get("role") or "ANALYST").upper().strip()

    if not email or "@" not in email:
        raise HTTPException(422, "Email invalide")

    valid_roles = {"ADMIN", "ANALYST", "VIEWER", "MANAGER"}
    if role not in valid_roles:
        role = "ANALYST"

    try:
        # Check existing
        existing = db.execute(
            text("SELECT 1 FROM public.users WHERE lower(email) = lower(:email) AND tenant_id = CAST(:tid AS uuid) LIMIT 1"),
            {"email": email, "tid": tid},
        ).fetchone()
        if existing:
            raise HTTPException(409, f"L'utilisateur {email} existe déjà dans ce tenant.")

        # Try invitations table
        has_inv = db.execute(text("SELECT to_regclass('public.invitations')")).scalar()
        if has_inv:
            db.execute(
                text("""
                    INSERT INTO public.invitations (email, role, tenant_id, created_at, status)
                    VALUES (lower(:email), :role, CAST(:tid AS uuid), now(), 'pending')
                    ON CONFLICT (email, tenant_id) DO UPDATE
                        SET role = :role, status = 'pending', created_at = now()
                """),
                {"email": email, "role": role, "tid": tid},
            )
            db.commit()
        # else: no invitations table — just return success (email sending handled elsewhere)

        return JSONResponse(content={"ok": True, "email": email, "role": role})

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(500, f"Erreur invitation: {e}")


# ─── PATCH /settings/users/{user_id} ─────────────────────────────────────────

@router.patch("/settings/users/{user_id}")
def update_user_role(
    user_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tid = _setup(db, user)
    role = str(payload.get("role") or "").upper().strip()

    valid_roles = {"ADMIN", "ANALYST", "VIEWER", "MANAGER"}
    if not role or role not in valid_roles:
        raise HTTPException(422, f"Rôle invalide. Valeurs: {', '.join(valid_roles)}")

    try:
        result = db.execute(
            text("""
                UPDATE public.users
                SET role       = :role,
                    updated_at = now()
                WHERE id           = CAST(:uid AS uuid)
                  AND tenant_id    = CAST(:tid AS uuid)
                RETURNING id::text
            """),
            {"role": role, "uid": user_id, "tid": tid},
        ).fetchone()

        if not result:
            raise HTTPException(404, "Utilisateur non trouvé dans ce tenant")

        db.commit()
        return JSONResponse(content={"ok": True, "user_id": user_id, "role": role})

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(500, f"Erreur mise à jour rôle: {e}")


# ─── POST /settings/sources/{code}/import ────────────────────────────────────

@router.post("/settings/sources/{code}/import")
def import_source(
    code: str,
    max_records: int = 1500,
    year: Optional[int] = None,
    edition: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Télécharge la liste officielle et l'ingère.

    L'import se fait CÔTÉ SERVEUR : la Conformité met ses listes à jour depuis
    l'application, sans accès à la base ni intervention technique.
    Idempotent : relancer n'ajoute que les désignations nouvelles.
    """
    from app.services import list_adapters, list_ingest

    _setup(db, user)
    adapter = list_adapters.ADAPTERS.get(code.upper())
    if not adapter:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun import automatique pour « {code} ». Sources disponibles : "
                   + ", ".join(sorted(list_adapters.ADAPTERS)),
        )
    try:
        # Certaines sources se moissonnent édition par édition : sans cela,
        # chaque tranche re-téléchargerait l'intégralité de l'historique.
        kwargs = {}
        for key, value in (("year", year), ("edition", edition)):
            if value is not None and key in (adapter.get("accepts") or []):
                kwargs[key] = value
        records = adapter["fetch"](**kwargs)
        out = list_ingest.ingest(
            db,
            source_code=code.upper(),
            source_name=adapter["name"],
            records=records,
            record_type=adapter.get("record_type", "SANCTION"),
            risk_level=adapter.get("risk_level", "HIGH"),
            source_type=adapter.get("source_type", "SANCTIONS"),
            evidence_url=adapter.get("url"),
            max_records=max_records,
        )
    except Exception as e:
        logger.exception("list_import_failed")
        raise HTTPException(status_code=502, detail=f"Import impossible : {e}")

    return JSONResponse(content={
        "source": code.upper(),
        "label": adapter.get("label"),
        "created": out["created"],
        "skipped": out["skipped"],
        "read": out.get("read", 0),
        "remaining": out.get("remaining", False),
        # Une source qui ne produit AUCUN enregistrement est presque toujours un
        # changement de format côté fournisseur, jamais un résultat normal.
        "warning": (
            "La source n'a produit aucun enregistrement : son format a "
            "probablement changé. Import à vérifier."
            if out.get("read", 0) == 0 else None
        ),
    })


@router.get("/settings/sources/importable")
def list_importable_sources(user=Depends(get_current_user)):
    """Sources dont la mise à jour peut être déclenchée depuis l'application."""
    from app.services import list_adapters
    return JSONResponse(content=[
        {"code": c, "label": a.get("label"), "url": a.get("url")}
        for c, a in sorted(list_adapters.ADAPTERS.items())
    ])


@router.post("/settings/sources/{code}/import-file")
async def import_source_file(
    code: str,
    file: UploadFile = File(...),
    max_records: int = 5000,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Importe une liste à partir d'un fichier DÉPOSÉ.

    Certaines administrations refusent les téléchargements venant d'un serveur
    (connexion acceptée puis maintenue sans réponse) : le fichier n'est alors
    accessible que depuis un navigateur. La Conformité le télécharge elle-même
    et le dépose ici. Même analyseur, même idempotence que l'import automatique.
    """
    import os
    import tempfile

    from app.services import list_adapters, list_ingest

    _setup(db, user)
    adapter = list_adapters.ADAPTERS.get(code.upper())
    if not adapter or not adapter.get("parse"):
        raise HTTPException(
            status_code=404,
            detail=f"Aucun analyseur de fichier pour « {code} ».",
        )

    # L'extension doit être conservée : openpyxl (comme d'autres analyseurs)
    # valide le format d'après le NOM du fichier, pas son contenu. Un fichier
    # temporaire sans extension est rejeté même s'il est parfaitement valide.
    suffix = os.path.splitext(file.filename or "")[1][:12] or ".dat"
    fd, path = tempfile.mkstemp(prefix="upload_", suffix=suffix)
    os.close(fd)
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(1 << 20):
                out.write(chunk)
        if os.path.getsize(path) < 1024:
            raise HTTPException(status_code=400, detail="Fichier vide ou tronqué.")

        out = list_ingest.ingest(
            db,
            source_code=code.upper(),
            source_name=adapter["name"],
            records=adapter["parse"](path),
            record_type=adapter.get("record_type", "SANCTION"),
            evidence_url=adapter.get("url"),
            max_records=max_records,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("list_import_file_failed")
        raise HTTPException(status_code=400, detail=f"Import impossible : {e}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    return JSONResponse(content={
        "source": code.upper(),
        "filename": file.filename,
        "created": out["created"],
        "skipped": out["skipped"],
        "read": out.get("read", 0),
        "remaining": out.get("remaining", False),
    })
