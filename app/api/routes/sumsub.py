# app/api/routes/sumsub.py

from __future__ import annotations

from datetime import datetime, timezone
import hmac
import hashlib
import json
from typing import Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app.core.config import settings

from app.api.deps.db import get_db_rls as get_db

from app.services.sumsub_client import SumsubClient, SumsubConfig
from app.models.case import Case

try:
    from app.models.audit import ProviderEvent  # type: ignore
except Exception:  # pragma: no cover
    ProviderEvent = None

router = APIRouter(prefix="/sumsub", tags=["sumsub"])


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def sumsub_client() -> SumsubClient:
    return SumsubClient(
        SumsubConfig(
            base_url=settings.SUMSUB_BASE_URL,
            app_token=settings.SUMSUB_APP_TOKEN,
            secret_key=settings.SUMSUB_SECRET_KEY,
        )
    )


def verify_sumsub_webhook(secret: str, body: bytes, sig_hex: str) -> bool:
    computed = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_hex, computed)


def _safe_uuid(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except Exception:
        return None


def _extract_review(obj: dict) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(obj, dict):
        return None, None

    review_status = obj.get("reviewStatus")
    rr = obj.get("reviewResult") or {}
    review_answer = rr.get("reviewAnswer") if isinstance(rr, dict) else None

    review = obj.get("review") or {}
    if isinstance(review, dict):
        review_status = review_status or review.get("reviewStatus")
        rr2 = review.get("reviewResult") or {}
        if not review_answer and isinstance(rr2, dict):
            review_answer = rr2.get("reviewAnswer")

    return (
        str(review_status) if review_status is not None else None,
        str(review_answer) if review_answer is not None else None,
    )


def _make_provider_event_id(payload: dict, event_type: str) -> Optional[str]:
    pid = payload.get("correlationId") or payload.get("eventId")
    if pid:
        return str(pid)

    inspection = payload.get("inspectionId") or ""
    created = payload.get("createdAtMs") or payload.get("createdAt") or ""
    fallback = f"{inspection}:{event_type}:{created}".strip(":")
    return fallback if fallback else None


def _find_case_from_webhook(payload: dict, db: Session) -> Tuple[Optional[Case], Optional[str], Optional[str]]:
    """
    ✅ Chez toi: externalUserId == Case.id (UUID)
    Priorité:
      1) applicantId -> Case.sumsub_applicant_id
      2) externalUserId (UUID) -> Case.id
    """
    applicant_id = payload.get("applicantId")
    applicant_id = str(applicant_id) if applicant_id else None

    external_user_id = payload.get("externalUserId")
    external_user_id = str(external_user_id) if external_user_id else None

    # (1) lookup par applicant_id
    if applicant_id:
        case = db.query(Case).filter(Case.sumsub_applicant_id == applicant_id).first()
        if case:
            return case, applicant_id, external_user_id

    # (2) lookup par externalUserId UUID -> Case.id
    ext_uuid = _safe_uuid(external_user_id)
    if ext_uuid:
        case = db.query(Case).filter(Case.id == ext_uuid).first()
        if case:
            if applicant_id and not getattr(case, "sumsub_applicant_id", None):
                case.sumsub_applicant_id = applicant_id
                db.add(case)
            return case, applicant_id, external_user_id

    return None, applicant_id, external_user_id


def enqueue_cascading_screening(case_id: str, db: Session) -> None:
    from app.services.cascading_screening import start_post_kyc_cascade
    req_id = start_post_kyc_cascade(case_id=case_id, db=db)
    print(f"[CASCADE] created screening_request_id={req_id} case_id={case_id}")


def _mark_sumsub_kyc_done(case_id: str, db: Session, final_answer: str) -> None:
    try:
        db.execute(
            text(
                """
                UPDATE screening_requests
                SET status = 'DONE',
                    completed_at = NOW(),
                    request_payload = jsonb_set(
                      COALESCE(request_payload, '{}'::jsonb),
                      '{sumsub_final_answer}',
                      to_jsonb(CAST(:ans AS text)),
                      true
                    )
                WHERE case_id = :cid
                  AND (request_payload->>'kind') = 'sumsub_kyc'
                  AND (status IS NULL OR status <> 'DONE')
                """
            ),
            {"cid": str(case_id), "ans": str(final_answer)},
        )
    except Exception as e:
        db.rollback()
        print("[WARN] failed to mark sumsub_kyc DONE:", e)


# -----------------------------------------------------------------------------
# SDK token (SDK-only)
# -----------------------------------------------------------------------------

class SDKTokenIn(BaseModel):
    case_id: str = Field(..., min_length=1, description="Case UUID")
    level_name: str = Field(..., min_length=1)
    ttl_in_secs: int = Field(600, ge=60, le=3600)


class SDKTokenOut(BaseModel):
    token: str
    case_id: str
    external_user_id: str
    level_name: str
    ttl_in_secs: int


@router.post("/sdk-token", response_model=SDKTokenOut)
async def create_websdk_token(payload: SDKTokenIn, db: Session = Depends(get_db)):
    # 1) validate case_id UUID
    try:
        cid = str(UUID(payload.case_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid case_id (must be UUID)")

    # 2) ensure case exists
    case = db.query(Case).filter(Case.id == cid).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    external_user_id = str(case.id)

    # 3) create token (SDK-only): userId/externalUserId
    client = sumsub_client()
    try:
        data = await client.generate_access_token_user(
            external_user_id=external_user_id,
            level_name=payload.level_name,
            ttl_in_seconds=payload.ttl_in_secs,
        )
        token = (data or {}).get("token")
        if not token:
            raise RuntimeError({"detail": "Sumsub access token response missing 'token'", "raw": data})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to create WebSDK token: {e}")

    return SDKTokenOut(
        token=str(token),
        case_id=str(case.id),
        external_user_id=external_user_id,
        level_name=payload.level_name,
        ttl_in_secs=payload.ttl_in_secs,
    )


# -----------------------------------------------------------------------------
# Webhook
# -----------------------------------------------------------------------------

@router.post("/webhook")
async def sumsub_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()

    sig = request.headers.get("x-payload-digest") or ""
    alg = request.headers.get("x-payload-digest-alg") or ""

    if not sig:
        raise HTTPException(status_code=400, detail="Missing signature header: x-payload-digest")
    if alg and alg != "HMAC_SHA256_HEX":
        raise HTTPException(status_code=400, detail=f"Unsupported signature alg: {alg}")

    if not verify_sumsub_webhook(settings.SUMSUB_WEBHOOK_SECRET, body, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = str(payload.get("type") or payload.get("eventType") or "unknown")

    # 1) audit event (dedup)
    if ProviderEvent is not None:
        applicant_id_for_event = payload.get("applicantId")
        applicant_id_for_event = str(applicant_id_for_event) if applicant_id_for_event else None
        provider_event_id = _make_provider_event_id(payload, event_type)

        try:
            db.add(
                ProviderEvent(
                    provider="sumsub",
                    external_id=applicant_id_for_event,
                    event_type=event_type,
                    payload=payload,
                    received_at=_now(),
                    provider_event_id=provider_event_id,
                )
            )
            db.flush()
        except IntegrityError:
            db.rollback()
            return {"ok": True, "deduped": True}

    # 2) find case
    case, applicant_id, external_user_id = _find_case_from_webhook(payload, db)

    if not case:
        db.commit()
        return {
            "ok": True,
            "linked": False,
            "reason": "no_case_match",
            "event_type": event_type,
            "applicant_id": applicant_id,
            "externalUserId": external_user_id,
        }

    # 3) stocker applicantId dès qu'on l'a (ex: applicantCreated)
    if applicant_id and not getattr(case, "sumsub_applicant_id", None):
        case.sumsub_applicant_id = applicant_id

    # 3bis) garder un snapshot du dernier payload (utile debug/support)
    try:
        case.sumsub_snapshot = payload
    except Exception:
        pass

    # 4) update review info si présent
    review_status, review_answer = _extract_review(payload)
    prev_answer = getattr(case, "sumsub_review_answer", None)

    if review_status:
        case.sumsub_review_status = review_status
    if review_answer:
        case.sumsub_review_answer = review_answer

    case.sumsub_last_event_at = _now()
    db.add(case)

    # 5) cascade on first GREEN
    cascade_triggered = False
    if review_answer == "GREEN" and prev_answer != "GREEN":
        enqueue_cascading_screening(str(case.id), db)
        cascade_triggered = True

    # 6) mark sumsub_kyc screening_request DONE
    if review_answer in ("GREEN", "RED", "YELLOW"):
        _mark_sumsub_kyc_done(str(case.id), db, review_answer)

    db.commit()

    return {
        "ok": True,
        "linked": True,
        "case_id": str(case.id),
        "event_type": event_type,
        "applicant_id": applicant_id,
        "externalUserId": external_user_id,
        "review_status": review_status,
        "review_answer": review_answer,
        "cascade_triggered": cascade_triggered,
    }
