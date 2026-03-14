# app/api/routes/screening.py
from __future__ import annotations

from uuid import UUID
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db

from app.schemas.screening import ScreeningCheckIn, ScreeningCheckOut
from app.services.simple_screening_engine import run_simple_screening

from app.models.document import Document, OCRStatus
from app.models.screening_db import ScreeningRequest, ScreeningResult, ScreeningMatch
from app.services.export_pdf_service import build_screening_pdf
from app.services.documents_service import apply_ocr_prefill_to_case
from app.core.db import set_tenant_context

router = APIRouter(prefix="/screening", tags=["screening"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _user_get(user: Any, key: str, default: str = "") -> str:
    if user is None:
        return default
    if isinstance(user, dict):
        v = user.get(key)
        return str(v) if v is not None else default
    v = getattr(user, key, None)
    return str(v) if v is not None else default


def _tenant_id(user: Any) -> str:
    tid = _user_get(user, "tenant_id", "")
    if tid:
        return tid
    return _user_get(user, "effective_tenant_id", "")


def _require_tenant_id(user: Any) -> str:
    tid = _tenant_id(user)
    if not tid:
        raise HTTPException(500, "current_user.tenant_id missing")
    return tid


def _require_user_id(user: Any) -> str:
    uid = _user_get(user, "id", "")
    if not uid:
        uid = _user_get(user, "user_id", "") or _user_get(user, "sub", "")
    if not uid:
        raise HTTPException(500, "current_user.id missing")
    return uid


def _extract_request_id(out: Any) -> Optional[str]:
    if isinstance(out, dict):
        return out.get("request_id") or out.get("id") or out.get("requestId")
    rid = getattr(out, "request_id", None) or getattr(out, "id", None)
    return str(rid) if rid else None


def _is_super_admin(user: dict) -> bool:
    return bool(user.get("is_super_admin"))


def _tenant_from_user(user: dict) -> str | None:
    tid = user.get("tenant_id")
    return str(tid) if tid else None


# ─── Case helpers ──────────────────────────────────────────────────────────────

def _pick_case_type(db: Session) -> str:
    rows = db.execute(
        text("""
            SELECT enumlabel FROM pg_enum
            WHERE enumtypid = 'case_type'::regtype
            ORDER BY enumsortorder ASC
        """)
    ).fetchall()
    labels = [r[0] for r in rows if r and r[0]]
    if not labels:
        return "KYC"
    for preferred in ("KYC", "SCREENING", "ONBOARDING", "CASE"):
        if preferred in labels:
            return preferred
    return labels[0]


def _pick_case_status(db: Session) -> str:
    try:
        rows = db.execute(
            text("""
                SELECT enumlabel FROM pg_enum
                WHERE enumtypid = 'case_status'::regtype
                ORDER BY enumsortorder ASC
            """)
        ).fetchall()
        labels = [r[0] for r in rows if r and r[0]]
        for preferred in ("DRAFT", "OPEN", "PENDING", "NEW"):
            if preferred in labels:
                return preferred
        return labels[0] if labels else "DRAFT"
    except Exception:
        return "DRAFT"


def _create_case_minimal(db: Session, created_by: str) -> str:
    case_type = _pick_case_type(db)
    status = _pick_case_status(db)
    row = db.execute(
        text("""
            INSERT INTO cases (case_type, created_by, status, created_at, updated_at)
            VALUES (
                CAST(:case_type AS case_type),
                CAST(:created_by AS uuid),
                CAST(:status AS case_status),
                NOW(), NOW()
            )
            RETURNING id::text
        """),
        {"case_type": case_type, "created_by": created_by, "status": status},
    ).fetchone()
    if not row:
        raise HTTPException(500, "Failed to create case")
    return str(row[0])


def _build_name(extracted: dict) -> str:
    full = (extracted.get("full_name") or "").strip()
    if full:
        return full
    first = (extracted.get("first_name") or "").strip()
    last = (extracted.get("last_name") or "").strip()
    return " ".join([first, last]).strip()


def _case_exists(db: Session, case_id: str) -> bool:
    try:
        r = db.execute(
            text("SELECT 1 FROM cases WHERE id::text = :cid LIMIT 1"),
            {"cid": case_id},
        ).fetchone()
        return bool(r)
    except Exception:
        return False


# ─── Schemas ──────────────────────────────────────────────────────────────────

class SimpleScreeningIn(BaseModel):
    entity_type: str  # "INDIVIDUAL" | "COMPANY"
    case_id: Optional[str] = None
    client_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    dob: Optional[str] = None
    nationality: Optional[str] = None
    country: Optional[str] = None
    company_name: Optional[str] = None
    registration_number: Optional[str] = None
    incorporation_country: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    include_aliases: bool = True
    max_matches: int = 20


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/simple", response_model=ScreeningCheckOut)
def screening_simple(
    payload: SimpleScreeningIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
):
    import traceback

    try:
        _require_tenant_id(user)
        created_by = _require_user_id(user)

        if x_tenant_id:
            if not _is_super_admin(user):
                raise HTTPException(403, "X-Tenant-Id requires SUPER_ADMIN")
            tenant_id = x_tenant_id
        else:
            tenant_id = _tenant_from_user(user)

        if not tenant_id:
            raise HTTPException(400, "tenant context missing")

        set_tenant_context(db, tenant_id)

        if payload.entity_type == "COMPANY":
            name = (payload.company_name or "").strip()
        else:
            name = f"{payload.first_name or ''} {payload.last_name or ''}".strip()

        if not name:
            raise HTTPException(422, "Missing name/company_name")

        # Resolve case_id
        if payload.case_id and str(payload.case_id).strip():
            candidate = str(payload.case_id).strip()
            if not _case_exists(db, candidate):
                raise HTTPException(status_code=404, detail="case_id not found")
            case_id = candidate
        else:
            try:
                case_id = _create_case_minimal(db, created_by)
                db.commit()
            except Exception as e:
                db.rollback()
                print("[SCREENING/SIMPLE] _create_case_minimal FAILED:", traceback.format_exc())
                raise HTTPException(500, f"Failed to create case: {e}")

        meta = {
            "trigger": "screening.simple",
            "entity_type": payload.entity_type,
            "dob": payload.dob,
            "nationality": payload.nationality,
            "country": payload.country,
            "aliases": payload.aliases,
            "include_aliases": payload.include_aliases,
            "max_matches": payload.max_matches,
            "registration_number": payload.registration_number,
            "incorporation_country": payload.incorporation_country,
            "case_id": case_id,
            "created_by": created_by,
            "client_name": name,
        }

        try:
            out = run_simple_screening(
                db=db,
                name=name,
                client_id=payload.client_id,
                country_focus=payload.country or payload.incorporation_country,
                meta=meta,
            )
        except Exception as e:
            print("[SCREENING/SIMPLE] run_simple_screening FAILED:", traceback.format_exc())
            raise HTTPException(500, f"Screening engine error: {e}")

        # ✅ FIX: UPDATE screening_requests avec rollback safe
        # run_simple_screening peut laisser la session en état "aborted"
        # sur les HIGH RISK screenings → rollback + re-poser tenant context
        request_id = _extract_request_id(out)
        if request_id:
            try:
                try:
                    db.rollback()
                except Exception:
                    pass
                set_tenant_context(db, tenant_id)

                db.execute(
                    text("""
                        UPDATE screening_requests
                        SET
                            case_id   = CAST(:case_id AS uuid),
                            client_id = COALESCE(client_id, :client_id)
                        WHERE id = CAST(:rid AS uuid)
                    """),
                    {
                        "case_id":   case_id,
                        "client_id": payload.client_id,
                        "rid":       str(request_id),
                    },
                )
                db.commit()
            except Exception as e:
                print("[SCREENING/SIMPLE] UPDATE screening_requests FAILED (non-bloquant):", e)
                db.rollback()

        return ScreeningCheckOut(**out)

    except HTTPException:
        raise
    except Exception as e:
        print("[SCREENING/SIMPLE] UNEXPECTED ERROR:", traceback.format_exc())
        raise HTTPException(500, f"Unexpected error: {e}")


@router.post("/check", response_model=ScreeningCheckOut)
def analyst_check(
    payload: ScreeningCheckIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_tenant_id(user)
    created_by = _require_user_id(user)

    out = run_simple_screening(
        db=db,
        name=payload.name,
        client_id=payload.client_id,
        country_focus=payload.country_focus,
        meta={
            "trigger": "analyst.screenings.check",
            "created_by": created_by,
        },
    )
    return ScreeningCheckOut(**out)


class ScreeningFromDocumentIn(BaseModel):
    document_id: UUID
    client_id: str | None = None
    country_focus: str | None = None
    override_name: str | None = None


@router.post("/from-document", response_model=ScreeningCheckOut)
def screening_from_document(
    payload: ScreeningFromDocumentIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_tenant_id(user)
    created_by = _require_user_id(user)

    doc = db.query(Document).filter(Document.id == payload.document_id).one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.ocr_status not in (OCRStatus.DONE, OCRStatus.LOW_CONFIDENCE):
        raise HTTPException(
            status_code=409,
            detail="OCR not completed. Call /documents/{id}/extract first.",
        )

    if doc.case_id:
        case_id = str(doc.case_id)
    else:
        try:
            case_id = _create_case_minimal(db, created_by)
            db.execute(
                text("UPDATE documents SET case_id = :cid WHERE id = :did"),
                {"cid": case_id, "did": str(doc.id)},
            )
            db.commit()
            db.refresh(doc)
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Failed to create/attach case: {e}")

    try:
        apply_ocr_prefill_to_case(
            db=db,
            case_id=case_id,
            extracted_fields=doc.extracted_fields or {},
            overwrite=False,
        )
    except Exception:
        db.rollback()

    name = (payload.override_name or "").strip() or _build_name(doc.extracted_fields or {})
    if not name:
        raise HTTPException(status_code=422, detail="No name extracted. Provide override_name.")

    out = run_simple_screening(
        db=db,
        name=name,
        client_id=payload.client_id,
        country_focus=payload.country_focus,
        meta={
            "trigger": "screening.from_document",
            "document_id": str(doc.id),
            "case_id": case_id,
            "created_by": created_by,
        },
    )
    return ScreeningCheckOut(**out)


@router.get("/{request_id}/export.json")
def export_screening_json(
    request_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_tenant_id(user)

    req = db.query(ScreeningRequest).filter(ScreeningRequest.id == request_id).one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Screening request not found")

    res     = db.query(ScreeningResult).filter(ScreeningResult.request_id == req.id).one_or_none()
    matches = db.query(ScreeningMatch).filter(ScreeningMatch.request_id == req.id).all()

    payload = {
        "request": {
            "id":              str(req.id),
            "client_id":       req.client_id,
            "request_payload": req.request_payload,
        },
        "result": None if not res else {
            "risk_level":          res.risk_level,
            "confidence":          res.confidence,
            "recommended_action":  res.recommended_action,
            "decided_by":          res.decided_by,
            "notes":               res.notes,
        },
        "matches": [
            {
                "entity_id":   str(m.entity_id),
                "match_score": m.match_score,
                "match_band":  m.match_band,
                "reasons":     m.reasons,
            }
            for m in matches
        ],
    }

    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="screening_{request_id}.json"'},
    )


@router.get("/{request_id}/export.pdf")
def export_pdf(
    request_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = _tenant_id(user)

    try:
        if db.in_transaction():
            db.rollback()
    except Exception:
        pass

    if tenant_id:
        set_tenant_context(db, tenant_id)

    try:
        pdf_bytes = build_screening_pdf(
            db,
            str(request_id),
            tenant_id=tenant_id,   # ⭐ IMPORTANT
        )

    except ValueError as e:
        print("[PDF VALUE ERROR]", e)
        raise HTTPException(status_code=500, detail=str(e))

    except Exception as e:
        import traceback
        print("[export_pdf] ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="screening-{request_id}.pdf"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )