# app/services/cascading_screening.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.case import Case

CASCADE_PROVIDER = "INTERNAL"
CASCADE_KIND = "post_kyc_green"


# -----------------------------
# Public API
# -----------------------------

def start_post_kyc_cascade(case_id: str, db: Session) -> str:
    """
    MVP: Create (idempotent) a screening_request "post_kyc_green" and run it immediately.

    - provider = INTERNAL
    - request_payload.kind = post_kyc_green
    - checks = sanctions + pep + adverse_media
    - status starts RUNNING
    - runner should set DONE + completed_at and write matches/results
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError("Case not found")

    # 1) Idempotence: return latest request for same case/kind/provider
    existing = db.execute(
        text(
            """
            SELECT id
            FROM screening_requests
            WHERE case_id = :case_id
              AND provider = :provider
              AND request_payload->>'kind' = :kind
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"case_id": str(case_id), "provider": CASCADE_PROVIDER, "kind": CASCADE_KIND},
    ).fetchone()

    if existing:
        request_id = str(existing[0])

        # Optionnel: si elle est encore RUNNING, on peut relancer le runner
        status_row = db.execute(
            text("SELECT status FROM screening_requests WHERE id = :id"),
            {"id": request_id},
        ).fetchone()
        if status_row and str(status_row[0]).upper() == "RUNNING":
            _run_screening_request_now(request_id=request_id, db=db)

        return request_id

    # 2) Create new request
    request_payload = {
        "kind": CASCADE_KIND,
        "trigger": "sumsub.applicantReviewed.GREEN",
        "checks": ["sanctions", "pep", "adverse_media"],
        "targets": [{"type": "case", "case_id": str(case_id)}],
        "options": {"include_aliases": True, "max_matches": 20},
    }

    now = datetime.now(timezone.utc)

    row = db.execute(
        text(
            """
            INSERT INTO screening_requests (
                client_id, request_payload, created_at, case_id,
                provider, triggered_by, status, completed_at
            )
            VALUES (
                :client_id, CAST(:request_payload AS jsonb), :created_at, :case_id,
                :provider, :triggered_by, :status, :completed_at
            )
            RETURNING id
            """
        ),
        {
            "client_id": getattr(case, "client_id", None),
            "request_payload": json_dumps(request_payload),
            "created_at": now,
            "case_id": str(case_id),
            "provider": CASCADE_PROVIDER,
            "triggered_by": None,
            "status": "RUNNING",
            "completed_at": None,
        },
    ).fetchone()

    if not row:
        raise RuntimeError("Failed to create screening_request")

    request_id = str(row[0])

    # Important: commit so the runner can reliably read the request
    db.commit()

    # 3) Run now (synchronous MVP)
    try:
        _run_screening_request_now(request_id=request_id, db=db)
    except Exception:
        # Optionnel: marquer FAILED si tu veux un état DB clair
        # (si ton runner gère déjà FAILED, tu peux enlever ce bloc)
        try:
            db.rollback()
            db.execute(
                text(
                    """
                    UPDATE screening_requests
                    SET status = 'FAILED',
                        completed_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": request_id, "now": datetime.now(timezone.utc)},
            )
            db.commit()
        except Exception:
            db.rollback()

        raise

    return request_id


# -----------------------------
# Helpers
# -----------------------------

def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _find_runner_callable() -> Callable[..., Any]:
    """
    Find a callable in app.services.screening_runner without guessing exact name.
    """
    from app.services import screening_runner as sr  # exists in your repo

    # Most likely function names
    candidates = [
        "run_screening_request",
        "run_request",
        "process_request",
        "run",
        "execute",
    ]

    for name in candidates:
        fn = getattr(sr, name, None)
        if callable(fn):
            return fn

    raise RuntimeError(
        "No runnable function found in app.services.screening_runner. "
        "Please expose one of: run_screening_request / run_request / process_request / run / execute."
    )


def _run_screening_request_now(request_id: str, db: Session) -> None:
    """
    Call screening runner right away (MVP).
    Tries multiple common signatures.
    """
    fn = _find_runner_callable()

    # Try common signatures
    try:
        fn(request_id=request_id, db=db)
        return
    except TypeError:
        pass

    try:
        fn(db=db, request_id=request_id)
        return
    except TypeError:
        pass

    try:
        fn(request_id, db)
        return
    except TypeError:
        pass

    try:
        fn(db, request_id)
        return
    except TypeError:
        pass

    # If still failing, raise a clearer error
    raise RuntimeError(
        f"Runner callable '{getattr(fn, '__name__', str(fn))}' found but signature not supported. "
        "Expected something like fn(request_id, db) or fn(request_id=request_id, db=db)."
    )
