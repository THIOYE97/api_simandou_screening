# app/services/simple_screening_engine.py
from __future__ import annotations

import uuid
from typing import Any, Optional
from uuid import UUID as UUID_T
import json
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.screening_db import ScreeningMatch, ScreeningRequest, ScreeningResult
from app.services.matching import (
    band,
    normalize_name,
    pick_best_source_record_id,
    retrieve_candidates,
    tokenize,
)

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _max_risk(risks: list[str]) -> str:
    if not risks:
        return "LOW"
    return max(risks, key=lambda r: RISK_ORDER.get(r, 0))


def _action_from(score: int, has_any: bool) -> str:
    if not has_any:
        return "PASS"
    if score >= 85:
        return "BLOCK"
    return "MANUAL_REVIEW"


def _as_uuid_or_none(v: Any) -> Optional[UUID_T]:
    if v in (None, "", "None", "null", "NULL"):
        return None
    if isinstance(v, UUID_T):
        return v
    try:
        return UUID_T(str(v))
    except Exception:
        return None


def _safe_case_uuid(meta: dict | None) -> Optional[UUID_T]:
    if not meta:
        return None
    return _as_uuid_or_none(meta.get("case_id"))


def _safe_triggered_by_uuid(meta: dict | None) -> Optional[UUID_T]:
    """
    Convention: les routes mettent meta["created_by"] = current_user.id (uuid str).
    On le mappe vers screening_requests.triggered_by.
    """
    if not meta:
        return None
    # compat: si tu changes de nom plus tard
    return _as_uuid_or_none(meta.get("created_by") or meta.get("triggered_by"))


def _set_if_attr(obj: Any, attr: str, value: Any) -> None:
    try:
        if hasattr(obj, attr):
            setattr(obj, attr, value)
    except Exception:
        pass


def _set_completed_at_now(db: Session, request_id: str) -> None:
    try:
        db.execute(
            text("UPDATE screening_requests SET completed_at = NOW() WHERE id = :rid"),
            {"rid": request_id},
        )
    except Exception:
        pass


def _current_tenant_uuid(db: Session) -> Optional[UUID_T]:
    val = db.execute(text("SELECT nullif(current_setting('app.tenant_id', true), '')")).scalar()
    if not val:
        return None
    try:
        return UUID_T(str(val))
    except Exception:
        return None


def _require_tenant_uuid(db: Session) -> UUID_T:
    tid = _current_tenant_uuid(db)
    if not tid:
        raise RuntimeError("tenant context missing (app.tenant_id is not set)")
    return tid


def _insert_result_sql(
    db: Session,
    *,
    tenant_id: UUID_T,
    result_id: UUID_T,
    request_id: UUID_T,
    risk_level: str,
    confidence: int,
    recommended_action: str,
    decided_by: str = "SYSTEM",
    notes: str | None = None,
) -> None:
    """
    Insert ScreeningResult in a way that always satisfies RLS:
    - If table has tenant_id -> include it
    - If not, fallback insert without tenant_id (for old schemas)
    """
    try:
        db.execute(
            text(
                """
                INSERT INTO screening_results
                  (id, tenant_id, request_id, risk_level, confidence, recommended_action, decided_by, notes)
                VALUES
                  (:id, :tenant_id, :request_id, :risk_level, :confidence, :recommended_action, :decided_by, :notes)
                """
            ),
            {
                "id": str(result_id),
                "tenant_id": str(tenant_id),
                "request_id": str(request_id),
                "risk_level": risk_level,
                "confidence": int(confidence),
                "recommended_action": recommended_action,
                "decided_by": decided_by,
                "notes": notes,
            },
        )
    except Exception:
        # fallback if schema has no tenant_id column
        db.execute(
            text(
                """
                INSERT INTO screening_results
                  (id, request_id, risk_level, confidence, recommended_action, decided_by, notes)
                VALUES
                  (:id, :request_id, :risk_level, :confidence, :recommended_action, :decided_by, :notes)
                """
            ),
            {
                "id": str(result_id),
                "request_id": str(request_id),
                "risk_level": risk_level,
                "confidence": int(confidence),
                "recommended_action": recommended_action,
                "decided_by": decided_by,
                "notes": notes,
            },
        )


def _insert_match_sql(
    db,
    *,
    tenant_id: str | None,
    request_id: str,
    entity_id: str,
    source_record_id: str | None,
    match_score: int,
    match_band: str,
    reasons: dict,
):
    sql = text(
        """
        INSERT INTO screening_matches
          (tenant_id, request_id, entity_id, source_record_id, match_score, match_band, reasons, created_at)
        VALUES
          (:tenant_id, :request_id, :entity_id, :source_record_id, :match_score, :match_band,
           CAST(:reasons AS jsonb), NOW())
        """
    )

    db.execute(
        sql,
        {
            "tenant_id": tenant_id,
            "request_id": request_id,
            "entity_id": entity_id,
            "source_record_id": source_record_id,
            "match_score": int(match_score),
            "match_band": match_band,
            "reasons": json.dumps(reasons),
        },
    )


def run_simple_screening(
    *,
    db: Session,
    name: str,
    client_id: Optional[str] = None,
    country_focus: Optional[str] = None,
    meta: dict | None = None,
) -> dict:
    tenant_id = _require_tenant_uuid(db)

    input_norm = normalize_name(name)
    input_tokens = tokenize(input_norm)
    case_uuid = _safe_case_uuid(meta)
    triggered_by_uuid = _safe_triggered_by_uuid(meta)

    # guardrail
    if len(input_norm) < 4 or len(input_tokens) < 2:
        req = ScreeningRequest(
            id=uuid.uuid4(),
            client_id=client_id,
            request_payload={
                "name": name,
                "name_normalized": input_norm,
                "country_focus": country_focus,
                "note": "input_too_short",
                "meta": meta or {},
            },
        )
        _set_if_attr(req, "tenant_id", tenant_id)
        _set_if_attr(req, "case_id", case_uuid)
        _set_if_attr(req, "triggered_by", triggered_by_uuid)  # ✅ NEW
        _set_if_attr(req, "provider", "INTERNAL")
        _set_if_attr(req, "status", "DONE")

        db.add(req)
        db.flush()

        result_id = uuid.uuid4()
        _insert_result_sql(
            db,
            tenant_id=tenant_id,
            result_id=result_id,
            request_id=req.id,
            risk_level="LOW",
            confidence=0,
            recommended_action="PASS",
            decided_by="SYSTEM",
            notes="input too short for reliable screening",
        )

        db.commit()

        return {
            "request_id": str(req.id),
            "risk_level": "LOW",
            "confidence": 0,
            "recommended_action": "PASS",
            "top_matches": [],
        }

    # 1) request
    req = ScreeningRequest(
        id=uuid.uuid4(),
        client_id=client_id,
        request_payload={
            "name": name,
            "name_normalized": input_norm,
            "country_focus": country_focus,
            "meta": meta or {},
        },
    )
    _set_if_attr(req, "tenant_id", tenant_id)
    _set_if_attr(req, "case_id", case_uuid)
    _set_if_attr(req, "triggered_by", triggered_by_uuid)  # ✅ NEW
    _set_if_attr(req, "provider", "INTERNAL")
    _set_if_attr(req, "status", "RUNNING")

    db.add(req)
    db.flush()

    try:
        # 2) candidates
        cands = retrieve_candidates(db, input_norm, input_tokens, limit=30)
        top = cands[:10]
        top_hits = [c for c in top if (c.score or 0) >= 60]

        # 3) matches
        for c in top_hits:
            ent_uuid = _as_uuid_or_none(getattr(c, "entity_id", None))
            if not ent_uuid:
                continue

            sr_id, src_id = pick_best_source_record_id(db, str(ent_uuid))
            sr_uuid = _as_uuid_or_none(sr_id)

            reasons = {
                "input_normalized": input_norm,
                "matched_normalized": getattr(c, "best_norm", None),
                "trigram_similarity": round(float(getattr(c, "trigram_sim", 0.0) or 0.0), 4),
                "token_overlap": round(float(getattr(c, "token_overlap", 0.0) or 0.0), 4),
                "primary_name": getattr(c, "primary_name", None),
                "best_name_id": getattr(c, "best_name_id", None),
                "source_record_id": str(sr_uuid) if sr_uuid else None,
                "source_id": src_id,
                "meta": meta or {},
            }

            # Prefer ORM if it supports tenant_id, else fall back to SQL
            m = ScreeningMatch(
                request_id=req.id,
                entity_id=ent_uuid,
                source_record_id=sr_uuid,
                match_score=int(c.score or 0),
                match_band=band(int(c.score or 0)),
                reasons=reasons,
            )
            if hasattr(m, "tenant_id"):
                _set_if_attr(m, "tenant_id", tenant_id)
                db.add(m)
            else:
                _insert_match_sql(
                    db,
                    tenant_id=str(tenant_id),
                    request_id=str(req.id),
                    entity_id=str(ent_uuid),
                    source_record_id=str(sr_uuid) if sr_uuid else None,
                    match_score=int(c.score or 0),
                    match_band=band(int(c.score or 0)),
                    reasons=reasons,
                )

        # 4) decision
        top_score = int(top_hits[0].score) if top_hits else 0
        recommended = _action_from(top_score, bool(top_hits))

        confidence = top_score if recommended != "PASS" else 0
        risk = _max_risk([str(getattr(c, "entity_risk", "LOW") or "LOW") for c in top_hits])

        _insert_result_sql(
            db,
            tenant_id=tenant_id,
            result_id=uuid.uuid4(),
            request_id=req.id,
            risk_level=risk,
            confidence=int(confidence),
            recommended_action=recommended,
            decided_by="SYSTEM",
            notes=None,
        )

        _set_if_attr(req, "status", "DONE")
        _set_completed_at_now(db, str(req.id))

        db.commit()

        return {
            "request_id": str(req.id),
            "risk_level": risk,
            "confidence": int(confidence),
            "recommended_action": recommended,
            "top_matches": [
                {
                    "entity_id": c.entity_id,
                    "entity_risk": c.entity_risk,
                    "primary_name": c.primary_name,
                    "score": int(c.score or 0),
                    "band": band(int(c.score or 0)),
                }
                for c in top_hits
            ],
        }

    except Exception as e:
        try:
            _set_if_attr(req, "status", "FAILED")
            db.commit()
        except Exception:
            db.rollback()
        raise e
