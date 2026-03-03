from fastapi import APIRouter, Depends, HTTPException, Header, Body
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.core.db import set_tenant_context
from app.core.security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_user)])


def _roles(db: Session, user: dict) -> set[str]:
    uid = str(user.get("id"))
    rows = db.execute(
        text("""
          SELECT role::text
          FROM user_roles
          WHERE user_id = :uid
        """),
        {"uid": uid},
    ).scalars().all()
    return set(rows)


def require_admin(db: Session, user: dict) -> set[str]:
    roles = _roles(db, user)
    if not roles & {"OWNER", "ADMIN", "SUPER_ADMIN"}:
        raise HTTPException(403, "admin role required")
    return roles


def require_super_admin(db: Session, user: dict) -> set[str]:
    roles = _roles(db, user)
    if "SUPER_ADMIN" not in roles:
        raise HTTPException(403, "super_admin role required")
    return roles


def _maybe_focus_tenant(db: Session, roles: set[str], x_tenant_id: str | None):
    """
    Si SUPER_ADMIN et X-Tenant-Id fourni -> switch tenant context.
    Sinon on laisse RLS/tenant courant.
    """
    if x_tenant_id:
        if "SUPER_ADMIN" not in roles:
            raise HTTPException(403, "X-Tenant-Id requires SUPER_ADMIN")
        set_tenant_context(db, x_tenant_id)


# ---------------------------------------------------------------------
# TENANTS
# ---------------------------------------------------------------------
@router.get("/tenants")
def list_tenants(db: Session = Depends(get_db), user=Depends(get_current_user)):
    roles = require_admin(db, user)

    # Si pas super admin: on renvoie juste le tenant courant (selon RLS)
    if "SUPER_ADMIN" not in roles:
        rows = db.execute(text("""
          SELECT id::text, name, slug, status, active_from, active_until, created_at, updated_at
          FROM tenants
          ORDER BY created_at DESC
          LIMIT 50
        """)).mappings().all()
        return [dict(r) for r in rows]

    # SUPER_ADMIN: tout
    rows = db.execute(text("""
      SELECT id::text, name, slug, status, active_from, active_until, created_at, updated_at
      FROM tenants
      ORDER BY created_at DESC
      LIMIT 500
    """)).mappings().all()
    return [dict(r) for r in rows]


@router.post("/tenants/{tenant_id}/suspend")
def suspend_tenant(tenant_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_super_admin(db, user)

    db.execute(text("""
      UPDATE tenants
      SET status = 'SUSPENDED'
      WHERE id = :tid
    """), {"tid": tenant_id})

    db.commit()
    return {"ok": True}


@router.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_super_admin(db, user)

    db.execute(text("""
      DELETE FROM tenants
      WHERE id = :tid
    """), {"tid": tenant_id})

    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------
@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,            # search email/full_name
    is_active: bool | None = None,
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    params = {"limit": limit, "offset": offset}

    where = ["1=1"]

    where.append("u.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid")

    if q:
        where.append("(u.email ILIKE :q OR u.full_name ILIKE :q)")
        params["q"] = f"%{q}%"
    if is_active is not None:
        where.append("u.is_active = :is_active")
        params["is_active"] = is_active

    rows = db.execute(text(f"""
      SELECT
        u.id::text,
        u.email,
        u.full_name,
        u.is_active,
        u.status,
        u.created_at,
        u.updated_at,
        u.tenant_id::text,
        COALESCE(array_agg(ur.role::text) FILTER (WHERE ur.role IS NOT NULL), '{{}}') AS roles
      FROM users u
      LEFT JOIN user_roles ur ON ur.user_id = u.id
      WHERE {" AND ".join(where)}
      GROUP BY u.id
      ORDER BY u.created_at DESC
      LIMIT :limit OFFSET :offset
    """), params).mappings().all()

    total = db.execute(text(f"""
      SELECT COUNT(*)
      FROM users u
      WHERE {" AND ".join(where)}
    """), params).scalar() or 0

    return {"items": [dict(r) for r in rows], "limit": limit, "offset": offset, "total": int(total)}

@router.get("/tenants/{tenant_id}/users")
def list_users_for_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    roles = require_admin(db, user)
    # si SUPER_ADMIN: on force le tenant
    _maybe_focus_tenant(db, roles, tenant_id)

    rows = db.execute(text("""
      SELECT id::text, email, full_name, is_active, status, tenant_id::text
      FROM users
      WHERE tenant_id = CAST(:tid AS uuid)
      ORDER BY created_at DESC
      LIMIT :limit OFFSET :offset
    """), {"tid": tenant_id, "limit": limit, "offset": offset}).mappings().all()

    return {"items": [dict(r) for r in rows], "limit": limit, "offset": offset}

@router.get("/users/{user_id}")
def get_user_admin(
    user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    row = db.execute(text("""
      SELECT
        u.id::text,
        u.email,
        u.full_name,
        u.is_active,
        u.status,
        u.created_at,
        u.updated_at,
        u.tenant_id::text,
        COALESCE(array_agg(ur.role::text) FILTER (WHERE ur.role IS NOT NULL), '{}') AS roles
      FROM users u
      LEFT JOIN user_roles ur ON ur.user_id = u.id
      WHERE u.id = CAST(:uid AS uuid)
      GROUP BY u.id
    """), {"uid": user_id}).mappings().first()

    if not row:
        raise HTTPException(404, "user not found")

    return dict(row)


@router.post("/users")
def create_user_admin(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    payload: dict = Body(...),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    email = (payload.get("email") or "").strip().lower()
    full_name = (payload.get("full_name") or "").strip()
    is_active = bool(payload.get("is_active", True))

    password = payload.get("password")  # <-- clair
    if isinstance(password, str):
        password = password.strip()

    if not email or not full_name:
        raise HTTPException(422, "email and full_name required")

    # tu peux rendre password obligatoire:
    if not password or len(password) < 8:
        raise HTTPException(422, "password required (min 8 chars)")

    tenant_id = payload.get("tenant_id")
    if tenant_id in ("", "null", "None"):
        tenant_id = None

    password_hash = hash_password(password)

    row = db.execute(text("""
      INSERT INTO users (email, full_name, password_hash, is_active, created_at, updated_at, tenant_id, status)
      VALUES (
        :email,
        :full_name,
        :password_hash,
        :is_active,
        NOW(),
        NOW(),
        COALESCE(
          CAST(:tenant_id AS uuid),
          NULLIF(current_setting('app.tenant_id', true), '')::uuid
        ),
        'ACTIVE'
      )
      RETURNING id::text, email, full_name, is_active, tenant_id::text, status
    """), {
        "email": email,
        "full_name": full_name,
        "password_hash": password_hash,
        "is_active": is_active,
        "tenant_id": tenant_id,
    }).mappings().first()

    if not row or not row.get("tenant_id"):
        db.rollback()
        raise HTTPException(400, "tenant_id is required (or set X-Tenant-Id / tenant context)")

    db.commit()
    return dict(row)

@router.post("/tenants")
def create_tenant(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # 👉 en général : seule une personne SUPER_ADMIN crée des tenants
    require_super_admin(db, user)

    name = (payload.get("name") or "").strip()
    slug = (payload.get("slug") or "").strip().lower()

    if not name or not slug:
        raise HTTPException(422, "name + slug required")

    # anti doublons
    existing = db.execute(text("""
      SELECT 1
      FROM tenants
      WHERE slug = :slug
      LIMIT 1
    """), {"slug": slug}).scalar()

    if existing:
        raise HTTPException(409, "tenant slug already exists")

    row = db.execute(text("""
      INSERT INTO tenants (name, slug, status, active_from, created_at, updated_at)
      VALUES (:name, :slug, 'ACTIVE', NOW(), NOW(), NOW())
      RETURNING id::text, name, slug, status, created_at
    """), {"name": name, "slug": slug}).mappings().first()

    db.commit()
    return dict(row)


@router.post("/users/{user_id}/disable")
def disable_user_admin(
    user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    db.execute(text("""
      UPDATE users SET is_active=false, updated_at=NOW()
      WHERE id = CAST(:uid AS uuid)
    """), {"uid": user_id})
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/enable")
def enable_user_admin(
    user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    db.execute(text("""
      UPDATE users SET is_active=true, updated_at=NOW()
      WHERE id = CAST(:uid AS uuid)
    """), {"uid": user_id})
    db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
):
    """
    ⚠️ Delete dur.
    (Si tu veux une suppression soft: on peut mettre status='DELETED' + anonymisation email)
    """
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    db.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    db.commit()
    return {"ok": True}

@router.post("/users/{user_id}/roles/add")
def add_role(
    user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    payload: dict = Body(...),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    role = (payload.get("role") or "").strip().upper()
    if role not in {"OWNER", "ADMIN", "SUPER_ADMIN", "ANALYST", "USER"}:
        raise HTTPException(422, "invalid role")

    # SUPER_ADMIN only for SUPER_ADMIN role assignment
    if role == "SUPER_ADMIN" and "SUPER_ADMIN" not in roles:
        raise HTTPException(403, "only SUPER_ADMIN can grant SUPER_ADMIN")

    db.execute(text("""
      INSERT INTO user_roles (user_id, role)
      VALUES (CAST(:uid AS uuid), CAST(:role AS user_role))
      ON CONFLICT DO NOTHING
    """), {"uid": user_id, "role": role})

    db.commit()
    return {"ok": True}

@router.post("/users/{user_id}/roles/remove")
def remove_role(
    user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    payload: dict = Body(...),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    role = (payload.get("role") or "").strip().upper()
    if role not in {"OWNER", "ADMIN", "SUPER_ADMIN", "ANALYST", "USER"}:
        raise HTTPException(422, "invalid role")

    if role == "SUPER_ADMIN" and "SUPER_ADMIN" not in roles:
        raise HTTPException(403, "only SUPER_ADMIN can revoke SUPER_ADMIN")

    db.execute(text("""
      DELETE FROM user_roles
      WHERE user_id = CAST(:uid AS uuid)
        AND role = CAST(:role AS user_role)
    """), {"uid": user_id, "role": role})

    db.commit()
    return {"ok": True}

# ---------------------------------------------------------------------
# SCREENINGS (listing enrichi)
# ---------------------------------------------------------------------
@router.get("/screenings")
def list_all_screenings(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    provider: str | None = None,
    triggered_by: str | None = None,
    risk_level: str | None = None,
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    rows = db.execute(
        text("""
          SELECT
            sr.id::text,
            sr.tenant_id::text,
            sr.created_at,
            sr.completed_at,
            sr.status,
            sr.provider,
            sr.client_id,
            sr.case_id::text,
            sr.triggered_by::text,
            u.email AS triggered_by_email,

            COALESCE(sr.request_payload->>'name', sr.request_payload->'meta'->>'client_name') AS screened_name,

            res.risk_level::text AS engine_risk_level,
            res.confidence AS engine_confidence,
            res.recommended_action::text AS engine_action,

            d.decision::text AS analyst_decision,
            d.comment::text AS analyst_comment,
            d.decided_by_email::text AS analyst_decided_by_email,
            d.decided_by_user_id::text AS analyst_decided_by_user_id,
            d.decided_at AS analyst_decided_at

          FROM screening_requests sr
          LEFT JOIN users u ON u.id = sr.triggered_by

          LEFT JOIN LATERAL (
            SELECT r.*
            FROM screening_results r
            WHERE r.request_id = sr.id
            ORDER BY r.decided_at DESC
            LIMIT 1
          ) res ON TRUE

          LEFT JOIN LATERAL (
            SELECT cd.*
            FROM case_screening_decisions cd
            WHERE cd.request_id = sr.id
               OR (sr.case_id IS NOT NULL AND cd.case_id = sr.case_id)
            ORDER BY cd.decided_at DESC NULLS LAST
            LIMIT 1
          ) d ON TRUE

          WHERE 1=1
            AND (CAST(:status AS text) IS NULL OR sr.status = CAST(:status AS text))
            AND (CAST(:provider AS text) IS NULL OR sr.provider = CAST(:provider AS text))
            AND (CAST(:risk_level AS text) IS NULL OR res.risk_level::text = CAST(:risk_level AS text))
            AND (
              CAST(:triggered_by AS uuid) IS NULL
              OR sr.triggered_by = CAST(:triggered_by AS uuid)
            )

          ORDER BY sr.created_at DESC
          LIMIT :limit OFFSET :offset
        """),
        {
            "limit": limit,
            "offset": offset,
            "status": status,
            "provider": provider,
            "triggered_by": triggered_by,
            "risk_level": risk_level,
        },
    ).mappings().all()

    return {"items": [dict(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/screenings/{request_id}")
def get_screening_admin(
    request_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    row = db.execute(text("""
      SELECT
        sr.id::text,
        sr.tenant_id::text,
        sr.created_at,
        sr.completed_at,
        sr.status,
        sr.provider,
        sr.client_id,
        sr.case_id::text,
        sr.triggered_by::text,
        u.email AS triggered_by_email,
        sr.request_payload
      FROM screening_requests sr
      LEFT JOIN users u ON u.id = sr.triggered_by
      WHERE sr.id = CAST(:rid AS uuid)
    """), {"rid": request_id}).mappings().first()

    if not row:
        raise HTTPException(404, "screening not found")

    # result
    res = db.execute(text("""
      SELECT risk_level::text, confidence, recommended_action::text, decided_by, decided_at, notes
      FROM screening_results
      WHERE request_id = CAST(:rid AS uuid)
      ORDER BY decided_at DESC
      LIMIT 1
    """), {"rid": request_id}).mappings().first()

    # decision
    dec = db.execute(text("""
      SELECT decision, comment, decided_by_email, decided_by_user_id::text, decided_at
      FROM case_screening_decisions
      WHERE request_id = CAST(:rid AS uuid)
      ORDER BY decided_at DESC
      LIMIT 1
    """), {"rid": request_id}).mappings().first()

    # matches
    matches = db.execute(text("""
      SELECT
        sm.id,
        sm.entity_id::text,
        sm.source_record_id::text,
        sm.match_score,
        sm.match_band::text,
        sm.reasons
      FROM screening_matches sm
      WHERE sm.request_id = CAST(:rid AS uuid)
      ORDER BY sm.match_score DESC
      LIMIT 200
    """), {"rid": request_id}).mappings().all()

    return {
      "request": dict(row),
      "result": dict(res) if res else None,
      "decision": dict(dec) if dec else None,
      "matches": [dict(m) for m in matches],
    }
@router.post("/users/{user_id}/reset-password")
def reset_password_admin(
    user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    payload: dict = Body(...),
):
    roles = require_admin(db, user)
    _maybe_focus_tenant(db, roles, x_tenant_id)

    password = payload.get("password")
    if isinstance(password, str):
        password = password.strip()

    if not password or len(password) < 8:
        raise HTTPException(422, "password required (min 8 chars)")

    password_hash = hash_password(password)

    db.execute(text("""
      UPDATE users
      SET password_hash = :ph, updated_at = NOW()
      WHERE id = CAST(:uid AS uuid)
    """), {"ph": password_hash, "uid": user_id})

    db.commit()
    return {"ok": True}
