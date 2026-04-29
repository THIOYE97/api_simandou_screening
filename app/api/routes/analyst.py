# app/api/routes/analyst.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
from io import StringIO
import csv

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import desc

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db

from app.models.case import Case
from app.models.screening_db import (
    Entity,
    ScreeningMatch,
    ScreeningRequest,
    ScreeningResult,
    SourceRecord,
)


router = APIRouter(
    prefix="/analyst",
    tags=["analyst"],
    dependencies=[Depends(get_current_user)],
)

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------

class ScreeningDetailsOut(BaseModel):
    request: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    matches: List[Dict[str, Any]] = Field(default_factory=list)
    case: Optional[Dict[str, Any]] = None

    decision_latest: Optional[Dict[str, Any]] = None
    decision_history: List[Dict[str, Any]] = Field(default_factory=list)




class ScreeningPollOut(BaseModel):
    request_id: str
    status: str
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    matches_count: int = 0
    has_result: bool = False


class ScreeningDecisionIn(BaseModel):
    decision: str  # "PASS" | "BLOCK"
    comment: str
    request_id: Optional[str] = None

class ScreeningDecisionOut(BaseModel):
    ok: bool = True
    case_id: str
    request_id: Optional[str] = None
    decision: str
    decided_by: str
    decided_at: datetime


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

SOURCE_FALLBACK = {1: "UN", 2: "OFAC", 3: "EU"}


def _as_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}")


def _safe_str(x) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() == "none" or s == "-":
        return None
    return s


def _safe_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _user_get(user: Any, key: str, default: Any = None) -> Any:
    """Compat: user peut être dict, pydantic, ou objet ORM."""
    if user is None:
        return default
    if isinstance(user, dict):
        return user.get(key, default)
    # pydantic v1/v2
    if hasattr(user, "model_dump"):
        try:
            d = user.model_dump()
            return d.get(key, default)
        except Exception:
            pass
    if hasattr(user, "dict"):
        try:
            d = user.dict()
            return d.get(key, default)
        except Exception:
            pass
    return getattr(user, key, default)


def _case_id_from_request_payload(req_payload: Any) -> Optional[str]:
    if not isinstance(req_payload, dict):
        return None
    meta = req_payload.get("meta") or {}
    if isinstance(meta, dict):
        cid = meta.get("case_id")
        if cid and str(cid).lower() != "none":
            return str(cid)
    cid2 = req_payload.get("case_id")
    if cid2 and str(cid2).lower() != "none":
        return str(cid2)
    return None


def _client_name_from_payload(req_payload: Any) -> Optional[str]:
    if not isinstance(req_payload, dict):
        return None
    override = (req_payload.get("override_name") or "").strip()
    if override:
        return override
    nm = (req_payload.get("name") or "").strip()
    if nm:
        return nm
    fn = (req_payload.get("first_name") or req_payload.get("firstName") or "").strip()
    ln = (req_payload.get("last_name") or req_payload.get("lastName") or "").strip()
    full = f"{fn} {ln}".strip()
    return full or None


def _normalize_band(band: Any) -> str | None:
    if band is None:
        return None
    v = str(band).upper().strip()
    if v in ("STRONG", "HIGH"):
        return "Forte"
    if v in ("MEDIUM", "MID"):
        return "Moyenne"
    if v in ("WEAK", "LOW"):
        return "Faible"
    return v or None


def _source_label(code: str | None, name: str | None) -> str | None:
    if name and str(name).strip():
        return str(name).strip()
    if not code:
        return None
    v = str(code).upper().strip()
    return {
        "UN": "Nations Unies (ONU)",
        "OFAC": "États-Unis (OFAC)",
        "EU": "Union Européenne",
        "LOCAL": "Source locale",
        "INTERNAL": "Interne",
    }.get(v, v)


def _humanize_match_reasons(reasons: Any) -> dict:
    if reasons is None:
        return {"bullets": ["Correspondance détectée par le moteur."], "raw": None}

    if isinstance(reasons, str):
        s = reasons.strip()
        return {"bullets": [s] if s else ["Correspondance détectée par le moteur."], "raw": reasons}

    if isinstance(reasons, list):
        bullets = []
        for it in reasons[:20]:
            if it is None:
                continue
            if isinstance(it, str) and it.strip():
                bullets.append(it.strip())
            else:
                bullets.append(str(it))
        return {"bullets": bullets[:12] or ["Correspondance détectée par le moteur."], "raw": reasons}

    if isinstance(reasons, dict):
        bullets: list[str] = []

        sim = reasons.get("trigram_similarity") or reasons.get("similarity")
        try:
            v = float(sim)
            pct = int(round((v * 100) if v <= 1 else v))
            bullets.append(f"Similarité nom (après normalisation) : {pct}%.")
        except Exception:
            pass

        tok = reasons.get("token_overlap")
        try:
            if tok is not None:
                bullets.append(f"Mots en commun (token overlap) : {int(tok)}.")
        except Exception:
            pass

        inp = reasons.get("input_normalized") or reasons.get("input")
        mat = reasons.get("matched_normalized") or reasons.get("matched") or reasons.get("primary_name")
        if inp and mat:
            bullets.append(f"Nom analysé : « {inp} » → trouvé : « {mat} ».")

        for k, label in [
            ("dob_match", "Date de naissance correspondante."),
            ("doc_match", "Numéro de document correspondant."),
            ("country_match", "Pays / nationalité correspondante."),
        ]:
            if reasons.get(k) is True:
                bullets.append(label)

        if not bullets:
            bullets.append("Correspondance détectée par le moteur (détails disponibles).")

        return {"bullets": bullets[:12], "raw": reasons}

    return {"bullets": ["Correspondance détectée par le moteur (détails disponibles)."], "raw": reasons}


def _case_display_name(c: Any) -> str | None:
    if not c:
        return None

    if isinstance(c, dict):
        for k in ("display_name", "client_name", "full_name", "name"):
            v = c.get(k)
            if v and str(v).strip():
                return str(v).strip()
        first = c.get("first_name") or c.get("firstName")
        last = c.get("last_name") or c.get("lastName")
        full = f"{str(first or '').strip()} {str(last or '').strip()}".strip()
        return full or None

    for attr in ("display_name", "client_name", "full_name", "name"):
        v = getattr(c, attr, None)
        if v and str(v).strip():
            return str(v).strip()

    first = getattr(c, "first_name", None) or getattr(c, "firstName", None)
    last = getattr(c, "last_name", None) or getattr(c, "lastName", None)
    full = f"{str(first or '').strip()} {str(last or '').strip()}".strip()
    return full or None


def _extract_sanction_reasons(sr: SourceRecord | None) -> dict:
    if not sr:
        return {"bullets": [], "raw": None}

    bullets: list[str] = []

    summary = getattr(sr, "summary", None)
    if isinstance(summary, str) and summary.strip():
        bullets.append(summary.strip())

    program = getattr(sr, "program", None)
    if program:
        bullets.append(f"Programme / régime : {program}")

    record_type = getattr(sr, "record_type", None)
    if record_type:
        bullets.append(f"Type d’enregistrement : {record_type}")

    listed_on = getattr(sr, "listed_on", None)
    if listed_on:
        bullets.append(f"Date d’inscription : {str(listed_on)}")

    unlisted_on = getattr(sr, "unlisted_on", None)
    if unlisted_on:
        bullets.append(f"Date de radiation : {str(unlisted_on)}")

    raw_payload = getattr(sr, "raw_payload", None)
    raw_excerpt = None

    if isinstance(raw_payload, dict):
        candidate_keys = [
            "reason", "reasons", "grounds", "narrative", "narrative_summary",
            "summary", "remarks", "comment", "designation_reason",
            "listing_reason", "basis",
        ]
        for k in candidate_keys:
            v = raw_payload.get(k)
            if isinstance(v, str) and v.strip():
                bullets.append(v.strip())
                break
            if isinstance(v, list) and v:
                vv = [str(x).strip() for x in v if x is not None and str(x).strip()]
                if vv:
                    bullets.append(" / ".join(vv[:3]))
                    break

        raw_excerpt = {}
        for k in [
            "source_code", "source_ref", "record_type", "program",
            "primary_name", "aliases", "nationality", "country",
            "dob", "birth_place", "identifiers",
            "reason", "reasons", "narrative_summary", "remarks", "summary",
        ]:
            if k in raw_payload:
                raw_excerpt[k] = raw_payload.get(k)

        if not raw_excerpt:
            raw_excerpt = {k: raw_payload.get(k) for k in list(raw_payload.keys())[:25]}
    else:
        if raw_payload is not None:
            raw_excerpt = raw_payload

    clean: list[str] = []
    seen = set()
    for b in bullets:
        key = b.strip().lower()
        if key and key not in seen:
            clean.append(b.strip())
            seen.add(key)

    return {"bullets": clean[:12], "raw": raw_excerpt}


def _build_source_block(sr: SourceRecord | None, code: str | None, name: str | None) -> dict | None:
    if not sr and not code and not name:
        return None

    label = _source_label(code, name)
    links = _safe_list(getattr(sr, "evidence_urls", None)) if sr else []
    links = [str(x) for x in links if x]

    return {
        "label": label,
        "code": code,
        "name": name,
        "ref": (getattr(sr, "source_ref", None) if sr else None),
        "record_type": (getattr(sr, "record_type", None) if sr else None),
        "program": (getattr(sr, "program", None) if sr else None),
        "listed_on": (str(getattr(sr, "listed_on", None)) if sr and getattr(sr, "listed_on", None) else None),
        "unlisted_on": (str(getattr(sr, "unlisted_on", None)) if sr and getattr(sr, "unlisted_on", None) else None),
        "summary": (getattr(sr, "summary", None) if sr else None),
        "links": links[:8],
    }


def _get_payload(req: ScreeningRequest) -> dict:
    p = getattr(req, "request_payload", None)
    return p if isinstance(p, dict) else {}


def _get_req_case_id(req: ScreeningRequest) -> str | None:
    if hasattr(req, "case_id"):
        cid = _safe_str(getattr(req, "case_id", None))
        if cid:
            return cid
    payload = _get_payload(req)
    meta = payload.get("meta") or {}
    return _safe_str(meta.get("case_id")) or _case_id_from_request_payload(payload)


def _get_kind(req: ScreeningRequest) -> str | None:
    payload = _get_payload(req)
    return _safe_str(payload.get("kind")) or _safe_str(payload.get("trigger"))


def _get_provider(req: ScreeningRequest) -> str | None:
    if hasattr(req, "provider"):
        v = _safe_str(getattr(req, "provider", None))
        if v:
            return v
    payload = _get_payload(req)
    meta = payload.get("meta") or {}
    return _safe_str(payload.get("provider")) or _safe_str(meta.get("provider")) or "INTERNAL"


def _get_status(req: ScreeningRequest) -> str | None:
    if hasattr(req, "status"):
        v = _safe_str(getattr(req, "status", None))
        if v:
            return v
    payload = _get_payload(req)
    return _safe_str(payload.get("status")) or None


def _normalize_decision(v: str) -> str:
    x = (v or "").strip().upper()
    if x not in ("PASS", "BLOCK"):
        raise HTTPException(status_code=422, detail="decision must be PASS or BLOCK")
    return x


def _require_comment(s: str) -> str:
    t = (s or "").strip()
    if len(t) < 4:
        raise HTTPException(status_code=422, detail="comment required (min 4 chars)")
    return t



def _ensure_decisions_table(db: Session) -> None:
    has_tbl = db.execute(text("SELECT to_regclass('public.case_screening_decisions')")).scalar()
    if not has_tbl:
        raise HTTPException(500, "case_screening_decisions table not found (run migration)")


def _load_case_decisions(db: Session, case_id: str | None, request_id: str | None = None):
    """
    Retourne (latest, history) depuis case_screening_decisions.
    SAFE: si transaction abort => rollback puis retry.
    Fallback: si request_id ne marche pas => essayer par case_id.
    """
    if not case_id and not request_id:
        return None, []

    # table exists ?
    try:
        has_tbl = db.execute(text("SELECT to_regclass('public.case_screening_decisions')")).scalar()
        if not has_tbl:
            return None, []
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None, []

    def _query_by_request(rid: str):
        return db.execute(
            text(
                """
                SELECT
                  decision,
                  comment,
                  decided_at,
                  decided_by_email,
                  decided_by_user_id::text AS decided_by_user_id,
                  request_id::text AS request_id,
                  case_id::text AS case_id
                FROM public.case_screening_decisions
                WHERE request_id = CAST(:rid AS uuid)
                ORDER BY decided_at DESC
                LIMIT 50
                """
            ),
            {"rid": rid},
        ).mappings().all()

    def _query_by_case(cid: str):
        return db.execute(
            text(
                """
                SELECT
                  decision,
                  comment,
                  decided_at,
                  decided_by_email,
                  decided_by_user_id::text AS decided_by_user_id,
                  request_id::text AS request_id,
                  case_id::text AS case_id
                FROM public.case_screening_decisions
                WHERE case_id = CAST(:cid AS uuid)
                ORDER BY decided_at DESC
                LIMIT 50
                """
            ),
            {"cid": cid},
        ).mappings().all()

    rows = []
    try:
        if request_id:
            rows = _query_by_request(request_id)
        if (not rows) and case_id:
            rows = _query_by_case(case_id)
    except Exception:
        # ✅ IMPORTANT: reset session state then retry once
        try:
            db.rollback()
        except Exception:
            pass

        try:
            if request_id:
                rows = _query_by_request(request_id)
            if (not rows) and case_id:
                rows = _query_by_case(case_id)
        except Exception:
            return None, []

    history = [dict(r) for r in rows] if rows else []
    latest = history[0] if history else None
    return latest, history


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

# Remplacement de la route GET /analyst/screenings dans analyst.py
# Copier/coller ce bloc pour remplacer la fonction list_screenings existante

@router.get("/screenings")
def list_screenings(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    provider: str | None = None,
    name: str | None = None,
    kind: str | None = None,
    risk_level: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Retour paginé compatible front:
      { items: [...], limit, offset, total }

    Filtres supportés:
      - status
      - provider
      - name
      - kind
      - risk_level

    Inclut:
      - risk_level
      - confidence
      - recommended_action
      - matches_count
      - client_name
    """

    status_norm = (status or "").strip().upper()
    provider_norm = (provider or "").strip()
    name_norm = (name or "").strip()
    kind_norm = (kind or "").strip()
    risk_norm = (risk_level or "").strip().upper()

    if status_norm in ("", "ALL"):
        status_norm = ""

    if risk_norm in ("", "ALL", "ALL_MATCHES"):
        risk_norm = ""

    status_map = {
        "TERMINE": "DONE",
        "TERMINÉ": "DONE",
        "DONE": "DONE",
        "PENDING": "PENDING",
        "RUNNING": "RUNNING",
        "FAILED": "FAILED",
        "ERROR": "ERROR",
    }

    risk_map = {
        "HIGH": "HIGH",
        "HIGH_RISK": "HIGH",
        "MEDIUM": "MEDIUM",
        "MEDIUM_RISK": "MEDIUM",
        "LOW": "LOW",
        "LOW_RISK": "LOW",
    }

    if status_norm:
        status_norm = status_map.get(status_norm, status_norm)

    if risk_norm:
        risk_norm = risk_map.get(risk_norm, risk_norm)

    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }

    sql = """
        WITH match_counts AS (
            SELECT
                request_id,
                COUNT(*)::int AS matches_count
            FROM public.screening_matches
            GROUP BY request_id
        ),
        base AS (
            SELECT
                sr.id::text AS id,
                sr.provider::text AS provider,
                sr.status::text AS status,
                sr.created_at AS created_at,
                sr.completed_at AS completed_at,
                sr.case_id::text AS case_id,
                sr.client_id::text AS client_id,
                sr.request_payload AS request_payload,

                res.risk_level::text AS risk_level,
                res.confidence AS confidence,
                res.recommended_action::text AS recommended_action,

                COALESCE(mc.matches_count, 0)::int AS matches_count,

                CASE
                    WHEN c.id IS NULL THEN NULL
                    ELSE to_jsonb(c)
                END AS case_payload

            FROM public.screening_requests sr
            LEFT JOIN public.screening_results res
                ON res.request_id = sr.id
            LEFT JOIN match_counts mc
                ON mc.request_id = sr.id
            LEFT JOIN public.cases c
                ON c.id = sr.case_id
            WHERE 1 = 1
    """

    if status_norm:
        sql += " AND UPPER(COALESCE(sr.status::text, '')) = :status"
        params["status"] = status_norm

    if provider_norm:
        sql += " AND UPPER(COALESCE(sr.provider::text, '')) = UPPER(:provider)"
        params["provider"] = provider_norm

    if risk_norm:
        sql += " AND UPPER(COALESCE(res.risk_level::text, '')) = :risk_level"
        params["risk_level"] = risk_norm

    if kind_norm:
        sql += """
            AND (
                sr.request_payload->>'kind' = :kind
                OR sr.request_payload->>'trigger' = :kind
            )
        """
        params["kind"] = kind_norm

    if name_norm:
        sql += """
            AND (
                sr.id::text ILIKE :name
                OR sr.request_payload->>'override_name' ILIKE :name
                OR sr.request_payload->>'name' ILIKE :name
                OR sr.request_payload->>'first_name' ILIKE :name
                OR sr.request_payload->>'last_name' ILIKE :name
                OR sr.request_payload->>'firstName' ILIKE :name
                OR sr.request_payload->>'lastName' ILIKE :name
                OR COALESCE(to_jsonb(c)->>'display_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'client_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'full_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'first_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'last_name', '') ILIKE :name
            )
        """
        params["name"] = f"%{name_norm}%"

    sql += """
        )
        SELECT
            *,
            COUNT(*) OVER()::int AS total_count
        FROM base
        ORDER BY created_at DESC NULLS LAST
        LIMIT :limit
        OFFSET :offset
    """

    try:
        rows = db.execute(text(sql), params).mappings().all()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(500, f"Failed to list screenings: {e}")

    items = []

    for row in rows:
        payload = row.get("request_payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        case_payload = row.get("case_payload") or {}
        if not isinstance(case_payload, dict):
            case_payload = {}

        first_name = (
            _safe_str(payload.get("first_name"))
            or _safe_str(payload.get("firstName"))
            or _safe_str(case_payload.get("first_name"))
            or _safe_str(case_payload.get("firstName"))
            or ""
        )

        last_name = (
            _safe_str(payload.get("last_name"))
            or _safe_str(payload.get("lastName"))
            or _safe_str(case_payload.get("last_name"))
            or _safe_str(case_payload.get("lastName"))
            or ""
        )

        full_from_parts = f"{first_name} {last_name}".strip()

        client_name = (
            _case_display_name(case_payload)
            or _safe_str(payload.get("override_name"))
            or _safe_str(payload.get("name"))
            or _client_name_from_payload(payload)
            or full_from_parts
            or None
        )

        item_kind = (
            _safe_str(payload.get("kind"))
            or _safe_str(payload.get("trigger"))
            or None
        )

        items.append({
            "id": row.get("id"),
            "provider": row.get("provider") or "INTERNAL",
            "status": row.get("status"),
            "created_at": row.get("created_at"),
            "completed_at": row.get("completed_at"),
            "case_id": row.get("case_id"),
            "client_id": row.get("client_id"),
            "kind": item_kind,
            "client_name": client_name,
            "first_name": first_name or None,
            "last_name": last_name or None,
            "risk_level": row.get("risk_level"),
            "confidence": row.get("confidence"),
            "recommended_action": row.get("recommended_action"),
            "matches_count": row.get("matches_count") or 0,
        })

    total = int(rows[0].get("total_count") or 0) if rows else 0

    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "total": total,
    }

@router.get("/screenings/export.csv")
def export_screenings_csv(
    status: str | None = Query(None),
    risk_level: str | None = Query(None),
    name: str | None = Query(None),
    provider: str | None = Query(None),
    kind: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Export CSV des screenings selon les filtres actifs dans la liste analyste.

    Exemples:
      /analyst/screenings/export.csv
      /analyst/screenings/export.csv?risk_level=HIGH
      /analyst/screenings/export.csv?risk_level=LOW&status=DONE
      /analyst/screenings/export.csv?status=RUNNING
    """

    status_norm = (status or "").strip().upper()
    risk_norm = (risk_level or "").strip().upper()
    provider_norm = (provider or "").strip()
    kind_norm = (kind or "").strip()
    name_norm = (name or "").strip()

    if status_norm in ("", "ALL"):
        status_norm = ""

    if risk_norm in ("", "ALL", "ALL_MATCHES"):
        risk_norm = ""

    status_map = {
        "TERMINE": "DONE",
        "TERMINÉ": "DONE",
        "DONE": "DONE",
        "PENDING": "PENDING",
        "RUNNING": "RUNNING",
        "FAILED": "FAILED",
        "ERROR": "ERROR",
    }

    risk_map = {
        "HIGH": "HIGH",
        "HIGH_RISK": "HIGH",
        "MEDIUM": "MEDIUM",
        "MEDIUM_RISK": "MEDIUM",
        "LOW": "LOW",
        "LOW_RISK": "LOW",
    }

    if status_norm:
        status_norm = status_map.get(status_norm, status_norm)

    if risk_norm:
        risk_norm = risk_map.get(risk_norm, risk_norm)

    params: dict[str, Any] = {}

    sql = """
        WITH match_counts AS (
            SELECT
                request_id,
                COUNT(*)::int AS matches_count
            FROM public.screening_matches
            GROUP BY request_id
        )
        SELECT
            sr.id::text AS id,
            sr.provider::text AS provider,
            sr.status::text AS status,
            sr.created_at AS created_at,
            sr.completed_at AS completed_at,
            sr.case_id::text AS case_id,
            sr.client_id::text AS client_id,
            sr.request_payload AS request_payload,

            res.risk_level::text AS risk_level,
            res.confidence AS confidence,
            res.recommended_action::text AS recommended_action,

            COALESCE(mc.matches_count, 0)::int AS matches_count,

            CASE
                WHEN c.id IS NULL THEN NULL
                ELSE to_jsonb(c)
            END AS case_payload

        FROM public.screening_requests sr
        LEFT JOIN public.screening_results res
            ON res.request_id = sr.id
        LEFT JOIN match_counts mc
            ON mc.request_id = sr.id
        LEFT JOIN public.cases c
            ON c.id = sr.case_id
        WHERE 1 = 1
    """

    if status_norm:
        sql += " AND UPPER(COALESCE(sr.status::text, '')) = :status"
        params["status"] = status_norm

    if provider_norm:
        sql += " AND UPPER(COALESCE(sr.provider::text, '')) = UPPER(:provider)"
        params["provider"] = provider_norm

    if risk_norm:
        sql += " AND UPPER(COALESCE(res.risk_level::text, '')) = :risk_level"
        params["risk_level"] = risk_norm

    if kind_norm:
        sql += """
            AND (
                sr.request_payload->>'kind' = :kind
                OR sr.request_payload->>'trigger' = :kind
            )
        """
        params["kind"] = kind_norm

    if name_norm:
        sql += """
            AND (
                sr.id::text ILIKE :name
                OR sr.request_payload->>'override_name' ILIKE :name
                OR sr.request_payload->>'name' ILIKE :name
                OR sr.request_payload->>'first_name' ILIKE :name
                OR sr.request_payload->>'last_name' ILIKE :name
                OR sr.request_payload->>'firstName' ILIKE :name
                OR sr.request_payload->>'lastName' ILIKE :name
                OR COALESCE(to_jsonb(c)->>'display_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'client_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'full_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'first_name', '') ILIKE :name
                OR COALESCE(to_jsonb(c)->>'last_name', '') ILIKE :name
            )
        """
        params["name"] = f"%{name_norm}%"

    sql += """
        ORDER BY sr.created_at DESC NULLS LAST
        LIMIT 10000
    """

    try:
        rows = db.execute(text(sql), params).mappings().all()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(500, f"Failed to export screenings: {e}")

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Screening ID",
        "Name",
        "Risk Level",
        "Status",
        "Provider",
        "Kind",
        "Confidence",
        "Recommended Action",
        "Matches Count",
        "Case ID",
        "Client ID",
        "Created At",
        "Completed At",
    ])

    for row in rows:
        payload = row.get("request_payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        case_payload = row.get("case_payload") or {}
        if not isinstance(case_payload, dict):
            case_payload = {}

        first_name = (
            _safe_str(payload.get("first_name"))
            or _safe_str(payload.get("firstName"))
            or _safe_str(case_payload.get("first_name"))
            or _safe_str(case_payload.get("firstName"))
            or ""
        )

        last_name = (
            _safe_str(payload.get("last_name"))
            or _safe_str(payload.get("lastName"))
            or _safe_str(case_payload.get("last_name"))
            or _safe_str(case_payload.get("lastName"))
            or ""
        )

        full_from_parts = f"{first_name} {last_name}".strip()

        client_name = (
            _case_display_name(case_payload)
            or _safe_str(payload.get("override_name"))
            or _safe_str(payload.get("name"))
            or _client_name_from_payload(payload)
            or full_from_parts
            or ""
        )

        item_kind = (
            _safe_str(payload.get("kind"))
            or _safe_str(payload.get("trigger"))
            or ""
        )

        writer.writerow([
            row.get("id") or "",
            client_name,
            row.get("risk_level") or "",
            row.get("status") or "",
            row.get("provider") or "",
            item_kind,
            row.get("confidence") or "",
            row.get("recommended_action") or "",
            row.get("matches_count") or 0,
            row.get("case_id") or "",
            row.get("client_id") or "",
            row.get("created_at") or "",
            row.get("completed_at") or "",
        ])

    output.seek(0)

    risk_part = risk_norm.lower() if risk_norm else "all"
    status_part = status_norm.lower() if status_norm else "all"
    filename = f"screenings_{risk_part}_{status_part}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )

@router.get("/screenings/{request_id}", response_model=ScreeningDetailsOut)
def screening_details(
    request_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # ✅ FIX: reset + tenant context
    try:
        db.rollback()
    except Exception:
        pass
    try:
        if isinstance(user, dict):
            _tid = user.get("tenant_id") or user.get("effective_tenant_id")
        else:
            _tid = getattr(user, "tenant_id", None) or getattr(user, "effective_tenant_id", None)
        if _tid:
            from app.core.db import set_tenant_context
            set_tenant_context(db, str(_tid))
    except Exception:
        pass
 
    rid = _as_uuid(request_id, "request_id")

    # ✅ 1) request en dict (pas ORM)
    req_row = db.execute(
        text("""
            SELECT
              id::text AS id,
              provider,
              status,
              created_at,
              completed_at,
              case_id::text AS case_id,
              client_id,
              request_payload
            FROM public.screening_requests
            WHERE id = CAST(:rid AS uuid)
            LIMIT 1
        """),
        {"rid": str(rid)},
    ).mappings().first()

    if not req_row:
        raise HTTPException(404, "screening_request not found")

    req_payload = req_row.get("request_payload") or {}
    if not isinstance(req_payload, dict):
        req_payload = {}

    case_id = _safe_str(req_row.get("case_id")) or _case_id_from_request_payload(req_payload)

    # ✅ 2) result en dict (pas ORM)
    res_row = db.execute(
        text("""
            SELECT
              id::text AS id,
              request_id::text AS request_id,
              risk_level,
              confidence,
              recommended_action,
              decided_by,
              decided_at,
              notes
            FROM public.screening_results
            WHERE request_id = CAST(:rid AS uuid)
            LIMIT 1
        """),
        {"rid": str(rid)},
    ).mappings().first()

    # ✅ 3) matches (déjà OK en mappings)
    m_rows = (
        db.execute(
            select(
                ScreeningMatch.id,
                ScreeningMatch.request_id,
                ScreeningMatch.entity_id,
                ScreeningMatch.source_record_id,
                ScreeningMatch.match_score,
                ScreeningMatch.match_band,
                ScreeningMatch.reasons,
                ScreeningMatch.created_at,
            )
            .where(ScreeningMatch.request_id == rid)
            .order_by(ScreeningMatch.created_at.desc(), ScreeningMatch.id.asc())
            .limit(200)
        )
        .mappings()
        .all()
    )

    entity_ids = list({r["entity_id"] for r in m_rows if r.get("entity_id")})
    sr_ids = list({r["source_record_id"] for r in m_rows if r.get("source_record_id")})

    entities_by_id: dict[str, Entity] = {}
    if entity_ids:
        ents = db.execute(select(Entity).where(Entity.id.in_(entity_ids))).scalars().all()
        entities_by_id = {str(e.id): e for e in ents}

    source_records_by_id: dict[str, SourceRecord] = {}
    if sr_ids:
        srs = db.execute(select(SourceRecord).where(SourceRecord.id.in_(sr_ids))).scalars().all()
        source_records_by_id = {str(s.id): s for s in srs}

    # ✅ 4) sources_map (safe)
    sources_map: dict[int, dict[str, str | None]] = {}
    try:
        has_sources = db.execute(text("SELECT to_regclass('public.sources')")).scalar()
        if has_sources:
            rows = db.execute(
                text("""
                    SELECT id::int AS id,
                           COALESCE(code::text, '') AS code,
                           COALESCE(name::text, '') AS name
                    FROM sources
                """)
            ).mappings().all()
            for r in rows:
                sid = int(r["id"])
                code = (r.get("code") or "").strip() or SOURCE_FALLBACK.get(sid, f"SOURCE_{sid}")
                name = (r.get("name") or "").strip() or None
                sources_map[sid] = {"code": code, "name": name}
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        sources_map = {}

    # ✅ 5) case + docs (safe, mais ne doit JAMAIS casser endpoint)
    documents = []
    case_info = None
    if case_id:
        try:
            c = db.execute(
                text("SELECT c.*, c.id::text AS id FROM cases c WHERE c.id = CAST(:cid AS uuid)"),
                {"cid": case_id},
            ).mappings().first()
            if c:
                case_info = dict(c)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            case_info = {"id": case_id}

        try:
            docs_rows = db.execute(
                text("""
                    SELECT
                      d.id::text AS id,
                      d.case_id::text AS case_id,
                      d.doc_type::text AS doc_type,
                      d.uploaded_at AS uploaded_at,
                      d.ocr_status::text AS ocr_status,
                      d.ocr_confidence AS ocr_confidence,
                      d.original_filename AS original_filename,
                      d.object_key AS object_key,
                      d.mime_type AS mime,
                      d.extracted_fields AS extracted_fields
                    FROM documents d
                    WHERE d.case_id = CAST(:cid AS uuid)
                    ORDER BY d.uploaded_at DESC
                    LIMIT 50
                """),
                {"cid": case_id},
            ).mappings().all()
            documents = [dict(r) for r in docs_rows]
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            documents = []

    request_payload_out = dict(req_payload)
    if documents:
        request_payload_out["documents"] = documents

    client_name = _client_name_from_payload(request_payload_out)

    # ✅ 6) décisions : SAFE + fallback request_id/case_id
    decision_latest, decision_history = _load_case_decisions(
        db,
        case_id=case_id,
        request_id=str(rid),
    )

    # ✅ 7) matches_out (inchangé)
    matches_out = []
    for r in m_rows:
        entity_id = str(r.get("entity_id") or "")
        sr_id = str(r.get("source_record_id") or "") if r.get("source_record_id") else None

        ent = entities_by_id.get(entity_id) if entity_id else None
        sr = source_records_by_id.get(sr_id) if sr_id else None

        sid = int(getattr(sr, "source_id", 0)) if sr else None
        scode = sources_map.get(sid, {}).get("code") if sid is not None else None
        sname = sources_map.get(sid, {}).get("name") if sid is not None else None

        match_reasons = _humanize_match_reasons(r.get("reasons"))
        sanction_reasons = _extract_sanction_reasons(sr)

        matches_out.append(
            {
                "id": r.get("id"),
                "request_id": str(r.get("request_id") or ""),
                "entity_id": entity_id or None,
                "entity_name": getattr(ent, "primary_name", None) if ent else None,
                "source_record_id": sr_id,
                "match_score": int(r.get("match_score") or 0),
                "match_band": r.get("match_band"),
                "match_band_label": _normalize_band(r.get("match_band")),
                "match_explain": match_reasons,
                "sanction_explain": sanction_reasons,
                "source_id": sid,
                "source_code": scode or (SOURCE_FALLBACK.get(sid) if sid else None),
                "source_name": sname,
                "source_ref": getattr(sr, "source_ref", None) if sr else None,
                "record_type": getattr(sr, "record_type", None) if sr else None,
                "program": getattr(sr, "program", None) if sr else None,
                "listed_on": (str(getattr(sr, "listed_on", None)) if sr and getattr(sr, "listed_on", None) else None),
                "unlisted_on": (str(getattr(sr, "unlisted_on", None)) if sr and getattr(sr, "unlisted_on", None) else None),
                "summary": getattr(sr, "summary", None) if sr else None,
                "evidence_urls": getattr(sr, "evidence_urls", None) if sr else None,
                "source_block": _build_source_block(sr, scode, sname),
                "created_at": r.get("created_at"),
            }
        )

    case_out = None
    if case_id:
        base_case = (case_info or {"id": case_id})
        case_out = {**base_case, "documents": documents}
        case_out["screening_decision"] = decision_latest
        case_out["screening_decision_history"] = decision_history

    return ScreeningDetailsOut(
        request={
            "id": req_row["id"],
            "provider": req_row.get("provider"),
            "status": req_row.get("status"),
            "created_at": req_row.get("created_at"),
            "completed_at": req_row.get("completed_at"),
            "case_id": case_id,
            "client_id": req_row.get("client_id"),
            "request_payload": request_payload_out,
            "client_name": client_name,
        },
        result=None
        if not res_row
        else {
            "id": res_row["id"],
            "request_id": res_row["request_id"],
            "risk_level": res_row.get("risk_level"),
            "confidence": int(res_row.get("confidence") or 0),
            "recommended_action": res_row.get("recommended_action"),
            "decided_by": res_row.get("decided_by"),
            "decided_at": res_row.get("decided_at"),
            "notes": res_row.get("notes"),
        },
        matches=matches_out,
        case=case_out,
        decision_latest=decision_latest,
        decision_history=decision_history,
    )
@router.post("/cases/{case_id}/screening-decision", response_model=ScreeningDecisionOut)
def set_case_screening_decision(
    case_id: str,
    payload: ScreeningDecisionIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    ✅ Nouveau endpoint: décision liée au CASE.
    - decision PASS/BLOCK + commentaire obligatoire
    - request_id optionnel (audit)
    - écrit uniquement dans case_screening_decisions
    """
    case_uuid = _as_uuid(case_id, "case_id")

    decision = _normalize_decision(payload.decision)
    comment = _require_comment(payload.comment)

    # request_id optionnel
    request_uuid: Optional[UUID] = None
    if payload.request_id:
        request_uuid = _as_uuid(payload.request_id, "request_id")

    email = (
        _safe_str(_user_get(user, "email", None))
        or _safe_str(_user_get(user, "username", None))
        or _safe_str(_user_get(user, "sub", None))
        or "unknown"
    )

    user_id = _safe_str(_user_get(user, "id", None)) or _safe_str(_user_get(user, "user_id", None)) or ""

    try:
        has_tbl = db.execute(text("SELECT to_regclass('public.case_screening_decisions')")).scalar()
        if not has_tbl:
            raise HTTPException(500, "case_screening_decisions table not found (run migration)")

        # (optionnel) check case exists si tu veux être strict:
        # exists_case = db.execute(text("SELECT 1 FROM cases WHERE id = :cid"), {"cid": str(case_uuid)}).scalar()
        # if not exists_case:
        #     raise HTTPException(404, "case not found")

        row = db.execute(
            text(
                """
                INSERT INTO case_screening_decisions
                  (case_id, request_id, decision, comment, decided_by_email, decided_by_user_id, decided_at)
                VALUES
                  (:case_id,
                   :request_id,
                   :decision,
                   :comment,
                   :email,
                   NULLIF(:user_id,'')::uuid,
                   now())
                RETURNING decided_at
                """
            ),
            {
                "case_id": str(case_uuid),
                "request_id": (str(request_uuid) if request_uuid else None),
                "decision": decision,
                "comment": comment,
                "email": email,
                "user_id": user_id or "",
            },
        ).mappings().first()

        db.commit()

        decided_at = row["decided_at"] if row and row.get("decided_at") else datetime.utcnow()

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Failed to save decision: {e}")

    return ScreeningDecisionOut(
        ok=True,
        case_id=str(case_uuid),
        request_id=(str(request_uuid) if request_uuid else None),
        decision=decision,
        decided_by=email,
        decided_at=decided_at,
    )

@router.post("/screenings/{request_id}/decision")
def set_screening_decision(
    request_id: str,
    payload: ScreeningDecisionIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Décision humaine PASS/BLOCK + commentaire obligatoire.
    Écrit uniquement dans case_screening_decisions.
    Retourne latest + history pour affichage immédiat.
    """
    rid = _as_uuid(request_id, "request_id")
    _ensure_decisions_table(db)

    # ✅ request en dict (pas ORM) pour éviter les objets expirables
    req_row = db.execute(
        text("""
            SELECT
              id::text AS id,
              case_id::text AS case_id,
              request_payload
            FROM public.screening_requests
            WHERE id = CAST(:rid AS uuid)
            LIMIT 1
        """),
        {"rid": str(rid)},
    ).mappings().first()

    if not req_row:
        raise HTTPException(404, "screening_request not found")

    req_payload = req_row.get("request_payload") or {}
    if not isinstance(req_payload, dict):
        req_payload = {}

    case_id = _safe_str(req_row.get("case_id")) or _case_id_from_request_payload(req_payload)
    if not case_id:
        raise HTTPException(409, "No case_id linked to this screening (cannot store decision history)")

    decision = _normalize_decision(payload.decision)
    comment = _require_comment(payload.comment)

    email = (
        _safe_str(_user_get(user, "email", None))
        or _safe_str(_user_get(user, "username", None))
        or _safe_str(_user_get(user, "sub", None))
        or "unknown"
    )
    user_id = _safe_str(_user_get(user, "id", None)) or _safe_str(_user_get(user, "user_id", None)) or ""

    # ✅ INSERT
    try:
        db.execute(
            text("""
                INSERT INTO public.case_screening_decisions
                  (case_id, request_id, decision, comment, decided_by_email, decided_by_user_id, decided_at)
                VALUES
                  (CAST(:case_id AS uuid),
                   CAST(:request_id AS uuid),
                   :decision,
                   :comment,
                   :email,
                   NULLIF(:user_id,'')::uuid,
                   now())
            """),
            {
                "case_id": case_id,
                "request_id": str(rid),
                "decision": decision,
                "comment": comment,
                "email": email,
                "user_id": user_id or "",
            },
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Failed to save decision: {e}")

    # ✅ reload decisions: by request_id first, fallback case_id
    latest, history = _load_case_decisions(db, request_id=str(rid), case_id=case_id)

    return {
        "ok": True,
        "case_id": case_id,
        "request_id": str(rid),
        "decision": decision,
        "decided_by": email,
        "decision_latest": latest,
        "decision_history": history,
    }
