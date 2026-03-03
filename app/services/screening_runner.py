from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import text


def run_screening_request_mvp(
    db: Session,
    request_id: str,
    simulate_match: bool = False,
) -> Tuple[str, int, str]:
    """
    Exécute un screening_request (MVP).
    Écrit:
      - screening_matches (optionnel, si simulate_match et entity_id trouvé)
      - screening_results (toujours)
      - met à jour cases.risk_level + last_screening_at
      - screening_requests.status=DONE + completed_at
    Retourne (risk_level, confidence, recommended_action).
    """

    # Charger request
    row = db.execute(
        text(
            """
            SELECT id, case_id, request_payload
            FROM screening_requests
            WHERE id = :id
            """
        ),
        {"id": request_id},
    ).fetchone()

    if not row:
        raise ValueError("screening_request not found")

    case_id = row[1]
    payload = row[2]  # dict (jsonb)

    # Trouver entity liée au case via case_entities
    entity_id = _try_get_entity_id_for_case(db, case_id)

    matches_created = 0

    # MVP: si simulate_match, on injecte un match HIGH (pour tester UI/workflow)
    if simulate_match and entity_id:
        db.execute(
            text(
                """
                INSERT INTO screening_matches (
                    request_id, entity_id, source_record_id, match_score, match_band, reasons, created_at
                )
                VALUES (
                    :request_id, :entity_id, :source_record_id, :match_score, :match_band, CAST(:reasons AS jsonb), :created_at
                )
                """
            ),
            {
                "request_id": request_id,
                "entity_id": entity_id,
                "source_record_id": None,
                "match_score": 82,
                "match_band": "HIGH",
                "reasons": json_dumps({
                    "kind": "simulated",
                    "checks": payload.get("checks", []),
                    "note": "Simulated match for MVP pipeline testing"
                }),
                "created_at": datetime.now(timezone.utc),
            },
        )
        matches_created = 1

    # Décision globale basée sur le meilleur match (si existant)
    risk_level, confidence, action = _decide_result(db, request_id)

    # Upsert screening_results (1 par request)
    existing_res = db.execute(
        text("SELECT id FROM screening_results WHERE request_id = :rid LIMIT 1"),
        {"rid": request_id},
    ).fetchone()

    notes = f"MVP runner. matches_created={matches_created}. checks={payload.get('checks', [])}"

    if existing_res:
        db.execute(
            text(
                """
                UPDATE screening_results
                SET risk_level = :risk_level,
                    confidence = :confidence,
                    recommended_action = :action,
                    decided_by = :decided_by,
                    decided_at = :decided_at,
                    notes = :notes
                WHERE request_id = :rid
                """
            ),
            {
                "rid": request_id,
                "risk_level": risk_level,
                "confidence": confidence,
                "action": action,
                "decided_by": "SYSTEM",
                "decided_at": datetime.now(timezone.utc),
                "notes": notes,
            },
        )
    else:
        db.execute(
            text(
                """
                INSERT INTO screening_results (
                    request_id, risk_level, confidence, recommended_action,
                    decided_by, decided_at, notes
                )
                VALUES (
                    :rid, :risk_level, :confidence, :action,
                    :decided_by, :decided_at, :notes
                )
                """
            ),
            {
                "rid": request_id,
                "risk_level": risk_level,
                "confidence": confidence,
                "action": action,
                "decided_by": "SYSTEM",
                "decided_at": datetime.now(timezone.utc),
                "notes": notes,
            },
        )

    # Met à jour le case (utile pour UI)
    ts = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            UPDATE cases
            SET risk_level = :risk_level,
                last_screening_at = :ts,
                updated_at = :ts
            WHERE id = :case_id
            """
        ),
        {"risk_level": risk_level, "ts": ts, "case_id": case_id},
    )

    # Mark request DONE
    db.execute(
        text(
            """
            UPDATE screening_requests
            SET status = :status,
                completed_at = :completed_at
            WHERE id = :id
            """
        ),
        {"status": "DONE", "completed_at": ts, "id": request_id},
    )

    db.commit()
    return risk_level, confidence, action


def _decide_result(db: Session, request_id: str) -> Tuple[str, int, str]:
    best = db.execute(
        text(
            """
            SELECT match_score, match_band
            FROM screening_matches
            WHERE request_id = :rid
            ORDER BY match_score DESC
            LIMIT 1
            """
        ),
        {"rid": request_id},
    ).fetchone()

    if not best:
        return "LOW", 90, "PASS"

    score, band = int(best[0]), str(best[1])

    if band == "HIGH" or score >= 80:
        return "HIGH", min(95, score), "ESCALATE"
    if band == "MEDIUM" or score >= 60:
        return "MEDIUM", min(90, score), "REVIEW"
    return "LOW", max(70, score), "PASS"


def _try_get_entity_id_for_case(db: Session, case_id: str) -> Optional[str]:
    row = db.execute(
        text(
            """
            SELECT entity_id
            FROM case_entities
            WHERE case_id = :cid
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"cid": case_id},
    ).fetchone()

    if row and row[0]:
        return str(row[0])
    return None


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)

def run_screening_request(request_id: str, db: Session) -> None:
    """
    Wrapper stable appelé par cascading_screening.
    Appelle la logique existante du runner.
    """
    # TODO: remplace "main" / "process" / "handle" par TA vraie fonction interne
    # Exemples possibles :
    # process_screening_request(request_id=request_id, db=db)
    # _run(request_id, db)
    # runner(request_id, db)

    return run_screening_request_mvp (request_id=request_id, db=db)  # <= change ce nom