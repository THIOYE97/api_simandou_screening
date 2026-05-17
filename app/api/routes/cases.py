from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import String, cast, select, text
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, keyset_paginate
from app.models.case import Case
from app.schemas.cases import CaseCreate, CaseDetail, CaseOut, CaseUpdate
from app.schemas.companies import CompanyOut, CompanyPersonCreate, CompanyUpsert
from app.schemas.persons import PersonOut, PersonUpsert
from app.services import cases_service


# ✅ dépendance globale: tout /cases nécessite un token
router = APIRouter(
    prefix="/cases",
    tags=["cases"],
    dependencies=[Depends(get_current_user)],
)
def get_default_user_id(db: Session):
    q = text("select id from users order by created_at asc limit 1")
    uid = db.execute(q).scalar()
    if not uid:
        raise HTTPException(status_code=400, detail="No users found. Create an admin user first.")
    return uid
@router.post("", response_model=CaseOut)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    created_by = user["id"]
    case = cases_service.create_case(db, payload.case_type, created_by=created_by)
    return case
# app/api/routes/cases.py
# Remplace UNIQUEMENT la route GET "" (list_cases)
# Supprime response_model pour éviter les conflits avec le schema CaseOut existant


@router.get("")
def list_cases(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    cursor: str | None = Query(
        default=None,
        description="Opaque keyset cursor. Use the next_cursor from the previous response.",
    ),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: Session = Depends(get_db),
):
    """
    Liste paginée des cases.

    Réponse :
      {
        "items":       [...],
        "next_cursor": "..." | null,
        "has_more":    bool
      }

    Tri stable : (created_at DESC, id DESC). Le `cursor` est opaque côté client.
    """
    base = select(Case)
    if status:
        base = base.where(Case.status == status)
    if q:
        base = base.where(cast(Case.id, String).ilike(f"%{q}%"))

    page = keyset_paginate(
        db,
        base_query=base,
        order_by=[Case.created_at.desc(), Case.id.desc()],
        limit=limit,
        cursor=cursor,
    )
    cases = page.items

    if not cases:
        return JSONResponse(content={"items": [], "next_cursor": None, "has_more": False})

    case_ids = [str(c.id) for c in cases]

    # ── Bulk: risk_level + recommended_action depuis screening_results ──
    risk_by_case: dict[str, str] = {}
    try:
        rows = db.execute(
            text("""
                SELECT DISTINCT ON (sr.case_id)
                    sr.case_id::text  AS case_id,
                    res.risk_level
                FROM public.screening_requests sr
                JOIN public.screening_results  res ON res.request_id = sr.id
                WHERE sr.case_id = ANY(CAST(:ids AS uuid[]))
                  AND res.risk_level IS NOT NULL
                ORDER BY sr.case_id, sr.created_at DESC
            """),
            {"ids": case_ids},
        ).mappings().all()
        risk_by_case = {r["case_id"]: r["risk_level"] for r in rows}
    except Exception:
        try: db.rollback()
        except Exception: pass

    # ── Bulk: client_name depuis screening_requests ──────────────────
    name_by_case: dict[str, str] = {}
    try:
        name_rows = db.execute(
            text("""
                SELECT DISTINCT ON (case_id)
                    case_id::text    AS case_id,
                    request_payload
                FROM public.screening_requests
                WHERE case_id = ANY(CAST(:ids AS uuid[]))
                ORDER BY case_id, created_at DESC
            """),
            {"ids": case_ids},
        ).mappings().all()

        for r in name_rows:
            payload = r.get("request_payload") or {}
            if isinstance(payload, dict):
                name = (
                    (payload.get("override_name") or "").strip()
                    or (payload.get("name") or "").strip()
                    or " ".join(filter(None, [
                        (payload.get("first_name") or "").strip(),
                        (payload.get("last_name")  or "").strip(),
                    ])).strip()
                    or (payload.get("client_name") or "").strip()
                )
                if name:
                    name_by_case[r["case_id"]] = name
    except Exception:
        try: db.rollback()
        except Exception: pass

    # ── Sérialisation manuelle (bypass Pydantic) ─────────────────────
    def _str(v) -> str | None:
        return str(v) if v is not None else None

    def _dt(v) -> str | None:
        if v is None: return None
        try: return v.isoformat()
        except Exception: return str(v)

    items = []
    for c in cases:
        cid = str(c.id)
        items.append({
            "id":          cid,
            "case_type":   _str(getattr(c, "case_type",  None)),
            "status":      _str(getattr(c, "status",     None)),
            "created_at":  _dt( getattr(c, "created_at", None)),
            "updated_at":  _dt( getattr(c, "updated_at", None)),
            "created_by":  _str(getattr(c, "created_by", None)),
            # ✅ enriched — nullable, no enum constraint
            "risk_level":  risk_by_case.get(cid),   # "HIGH" | "MEDIUM" | "LOW" | None
            "client_name": name_by_case.get(cid),   # str | None
        })

    return JSONResponse(content={
        "items": items,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    })


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: UUID, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    detail = {"case": case, "person": None, "company": None, "company_people": [], "documents": []}

    # person
    try:
        primary = db.execute(
            text("select entity_id from case_entities where case_id=:c and role='PRIMARY_PERSON' limit 1"),
            {"c": str(case_id)}
        ).mappings().first()

        if primary:
            row = db.execute(
                text("select * from persons where entity_id=:e"),
                {"e": str(primary["entity_id"])}
            ).mappings().first()
            if row:
                detail["person"] = dict(row)
    except Exception:
        pass

    # company + people
    try:
        primary = db.execute(
            text("select entity_id from case_entities where case_id=:c and role='PRIMARY_COMPANY' limit 1"),
            {"c": str(case_id)}
        ).mappings().first()

        if primary:
            row = db.execute(
                text("select * from companies where entity_id=:e"),
                {"e": str(primary["entity_id"])}
            ).mappings().first()
            if row:
                detail["company"] = dict(row)

            people = db.execute(text("""
                select cp.id, cp.role_type, cp.ownership_pct,
                       p.entity_id as person_entity_id, p.last_name, p.first_names
                from company_people cp
                join companies c on c.id = cp.company_id
                join persons p on p.id = cp.person_id
                where c.entity_id = :eid
                order by cp.created_at desc
            """), {"eid": str(primary["entity_id"])}).mappings().all()

            detail["company_people"] = [dict(x) for x in people]
    except Exception:
        pass

    # ✅ fix: text() obligatoire
    docs = db.execute(
        text("select * from documents where case_id=:c order by uploaded_at desc"),
        {"c": str(case_id)}
    ).mappings().all()
    detail["documents"] = [dict(d) for d in docs]

    return detail

@router.patch("/{case_id}", response_model=CaseOut)
def update_case(case_id: UUID, payload: CaseUpdate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(case, k, v)

    db.commit()
    db.refresh(case)
    return case

# app/api/routes/cases.py
# Remplace la route PATCH "/{case_id}/status" par cette version corrigée
# Utilise l'ORM (comme PATCH /{case_id} existant) au lieu de raw SQL
# → RLS est respecté automatiquement via la session ORM

@router.patch("/{case_id}/status")
def update_case_status(
    case_id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Change le statut : PENDING → IN_PROGRESS → CLOSED.
    ORM (pas raw SQL) → RLS respecté automatiquement.
    """
    # Valeurs valides de l'enum case_status
    try:
        valid_rows = db.execute(
            text("""
                SELECT enumlabel FROM pg_enum
                WHERE enumtypid = 'case_status'::regtype
                ORDER BY enumsortorder
            """)
        ).fetchall()
        valid_values = [r[0] for r in valid_rows]
    except Exception:
        valid_values = ["DRAFT", "OPEN", "PENDING", "IN_PROGRESS", "CLOSED", "DONE", "APPROVED"]

    new_status = str(payload.get("status", "")).strip().upper()

    # Mapping frontend → candidats enum DB
    STATUS_CANDIDATES = {
        "PENDING":     ["DRAFT", "OPEN", "PENDING", "NEW"],
        "IN_PROGRESS": ["IN_PROGRESS", "RUNNING", "ACTIVE"],
        "CLOSED":      ["CLOSED", "DONE", "APPROVED", "COMPLETED"],
    }

    candidates = STATUS_CANDIDATES.get(new_status)
    if not candidates:
        raise HTTPException(422, f"Status invalide. Valeurs: PENDING, IN_PROGRESS, CLOSED")

    # Premier candidat présent dans l'enum réel
    mapped = next((c for c in candidates if c in valid_values), None)
    if not mapped:
        # Fallback fuzzy
        kw = new_status.split("_")[0].lower()
        mapped = next((v for v in valid_values if kw in v.lower()), None)

    if not mapped:
        raise HTTPException(
            422,
            f"Impossible de mapper '{new_status}'. Enum DB: {valid_values}"
        )

    # ✅ ORM — respecte RLS (identique au PATCH /{case_id} existant)
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")

    try:
        setattr(case, "status", mapped)
        db.commit()
        db.refresh(case)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Erreur: {e}")

    from fastapi.responses import JSONResponse
    return JSONResponse(content={
        "ok":        True,
        "case_id":   str(case_id),
        "status":    new_status,
        "db_status": mapped,
    })
 
@router.put("/{case_id}/person", response_model=PersonOut)
def upsert_person(case_id: UUID, payload: PersonUpsert, db: Session = Depends(get_db)):
    try:
        return cases_service.upsert_person_for_case(db, case_id, payload.dict(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{case_id}/company", response_model=CompanyOut)
def upsert_company(case_id: UUID, payload: CompanyUpsert, db: Session = Depends(get_db)):
    try:
        return cases_service.upsert_company_for_case(db, case_id, payload.dict(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{case_id}/company/people")
def add_company_person(case_id: UUID, payload: CompanyPersonCreate, db: Session = Depends(get_db)):
    try:
        link = cases_service.add_company_person(
            db=db,
            case_id=case_id,
            person_entity_id=payload.person_entity_id,
            role_type=payload.role_type,
            ownership_pct=payload.ownership_pct,
        )
        return {"id": str(link.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))