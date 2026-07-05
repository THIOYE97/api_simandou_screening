"""
Passerelle Screening (KYC/KYB) → Alerte.

Quand un screening produit une correspondance (match) suffisante, on crée une
évaluation de risque (M7) et on génère une alerte (M6) : le dossier est ainsi
transmis à la Conformité, avec le nom du client, les motifs et le matching.
La DÉCISION appartient à la Conformité (sur l'alerte), pas à l'analyste.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.scoring import SubjectType
from app.services import alerting_service, scoring_service

# Seuil de score à partir duquel une correspondance déclenche une alerte.
MATCH_ALERT_THRESHOLD = 65


def raise_alerts_for_screening(
    db: Session,
    request_id: str,
    subject_label: str,
    entity_type: Optional[str] = None,
    tenant_id: Optional[UUID] = None,
    created_by: Optional[UUID] = None,
) -> list:
    """Crée une alerte si le screening comporte une correspondance ≥ seuil."""
    rows = db.execute(
        text("""
            SELECT sm.match_score, sm.match_band, sm.reasons,
                   e.primary_name AS entity_name, e.source_name,
                   sr.program, sr.record_type
            FROM screening_matches sm
            LEFT JOIN entities e ON e.id = sm.entity_id
            LEFT JOIN source_records sr ON sr.id = sm.source_record_id
            WHERE sm.request_id = CAST(:rid AS uuid)
            ORDER BY sm.match_score DESC
            LIMIT 20
        """),
        {"rid": str(request_id)},
    ).mappings().all()

    if not rows:
        return []
    top_score = int(rows[0]["match_score"] or 0)
    if top_score < MATCH_ALERT_THRESHOLD:
        return []

    is_pep = any(str(r["record_type"] or "").upper() == "PEP" for r in rows)
    subject_type = SubjectType.COMPANY if str(entity_type or "").upper() in ("COMPANY", "KYB") else SubjectType.PERSON

    context = {"match_score": top_score, "is_pep": is_pep, "match_count": len(rows)}
    assessment = scoring_service.score_subject(
        db, subject_type=subject_type, context=context,
        subject_ref=str(request_id), subject_label=subject_label,
        created_by=created_by, tenant_id=tenant_id, persist=True,
    )
    alerts = alerting_service.generate_from_assessment(db, assessment)

    # Enrichit chaque alerte avec le détail des correspondances (nom, source, motifs).
    def _reasons(val) -> list:
        if isinstance(val, dict):
            return val.get("bullets") or []
        if isinstance(val, list):
            return [str(x) for x in val]
        return []

    matches_summary = []
    for r in rows[:10]:
        matches_summary.append({
            "name": r["entity_name"],
            "source": r["source_name"],
            "program": r["program"],
            "record_type": r["record_type"],
            "score": int(r["match_score"] or 0),
            "band": r["match_band"],
            "reasons": _reasons(r["reasons"]),
        })
    for a in alerts:
        d = dict(a.detail or {})
        d["screening"] = {"request_id": str(request_id), "subject_label": subject_label, "matches": matches_summary}
        a.detail = d
    if alerts:
        db.commit()

    return alerts
