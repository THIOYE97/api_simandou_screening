"""
Service métier — Module 5 KYT (comportements atypiques) + Déclaration de soupçon.

Pipeline d'une transaction :
1. ingestion (depuis T24/SWIFT/ACH/RTGS ou manuel) ;
2. construction du contexte + détection de motifs (structuring) ;
3. scoring (M7) en sujet TRANSACTION → historisation ;
4. génération d'alertes (M6).
La Déclaration de soupçon (SAR) est gérée séparément (workflow Cellule Conformité).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.kyt import (
    SARDecision,
    SARStatus,
    SourceSystem,
    SuspiciousActivityReport,
    Transaction,
)
from app.models.scoring import SubjectType
from app.services import alerting_service, scoring_service

logger = logging.getLogger("simandou.kyt")

# Paramètres de détection (paramétrables — alignés sur le référentiel M1)
STRUCTURING_THRESHOLD = Decimal("10000")
STRUCTURING_WINDOW_DAYS = 7
STRUCTURING_MIN_COUNT = 3


# ---------------------------------------------------------------------------
# Filtrage des parties (émetteur / bénéficiaire) contre les listes
# ---------------------------------------------------------------------------
# On réutilise le MÊME moteur et les MÊMES listes que le KYC/KYS (OFAC, ONU,
# UE, PPE) : une opération dont une partie figure sur une liste doit déclencher
# les scénarios « Correspondance liste de sanction » et « PPE », au même titre
# qu'une vérification de personne.

_PARTY_MATCH_SQL = text("""
    SELECT sm.match_score, sm.match_band, sm.reasons,
           e.primary_name AS entity_name, e.source_name,
           sr.program, sr.record_type
    FROM screening_matches sm
    LEFT JOIN entities e ON e.id = sm.entity_id
    LEFT JOIN source_records sr ON sr.id = sm.source_record_id
    WHERE sm.request_id = CAST(:rid AS uuid)
    ORDER BY sm.match_score DESC
    LIMIT 10
""")


def _screenable(name: Optional[str]) -> bool:
    """Écarte les identifiants/références qui ne sont pas des noms de personne."""
    clean = (name or "").strip()
    return len(clean) >= 4 and len(clean.split()) >= 2


def _screen_party(
    db: Session, *, name: str, role: str,
    tenant_id: Optional[UUID] = None, country: Optional[str] = None,
) -> Optional[dict]:
    """Confronte une partie à l'opération aux listes. None si rien d'exploitable."""
    from app.core.db import set_tenant_context
    from app.services.simple_screening_engine import run_simple_screening

    try:
        # Le moteur exige le contexte tenant (RLS). Chaque commit rend la
        # connexion au pool et perd le GUC app.tenant_id : on le repose donc
        # juste avant CHAQUE filtrage.
        if tenant_id:
            set_tenant_context(db, str(tenant_id))
        res = run_simple_screening(
            db=db, name=name.strip(), country_focus=country,
            meta={"trigger": "kyt.party_screening", "role": role},
        )
        rows = db.execute(_PARTY_MATCH_SQL, {"rid": str(res["request_id"])}).mappings().all()
    except Exception:
        # Le filtrage ne doit jamais empêcher l'ingestion d'une opération.
        logger.exception("kyt_party_screening_failed", extra={"role": role})
        return None

    if not rows:
        return None
    return {
        "role": role,
        "name": name.strip(),
        "request_id": str(res["request_id"]),
        "score": int(rows[0]["match_score"] or 0),
        "is_pep": any(str(r["record_type"] or "").upper() == "PEP" for r in rows),
        "matches": [
            {
                "name": r["entity_name"], "source": r["source_name"], "program": r["program"],
                "record_type": r["record_type"], "score": int(r["match_score"] or 0),
                "band": r["match_band"], "party": role,
            }
            for r in rows
        ],
    }


def screen_parties(db: Session, txn: Transaction) -> list[dict]:
    """Filtre l'émetteur (client) ET le bénéficiaire de l'opération."""
    out = []
    for role, raw in (("Émetteur", txn.customer_ref), ("Bénéficiaire", txn.counterparty_name)):
        if not _screenable(raw):
            continue
        hit = _screen_party(
            db, name=raw, role=role,
            tenant_id=txn.tenant_id, country=txn.counterparty_country,
        )
        if hit:
            out.append(hit)
    return out


def _detect_structuring(db: Session, txn: Transaction) -> bool:
    """
    Fractionnement : plusieurs opérations juste sous le seuil de déclaration
    par le même client sur une fenêtre glissante.
    """
    if not txn.customer_ref:
        return False
    lower = STRUCTURING_THRESHOLD * Decimal("0.5")
    since = datetime.now(timezone.utc) - timedelta(days=STRUCTURING_WINDOW_DAYS)
    count = db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.customer_ref == txn.customer_ref,
            Transaction.amount >= lower,
            Transaction.amount < STRUCTURING_THRESHOLD,
            Transaction.created_at >= since,
        )
    ).scalar_one()
    # `count` inclut la transaction courante (déjà persistée avant analyse)
    return count >= STRUCTURING_MIN_COUNT


def analyze_transaction(db: Session, txn: Transaction):
    """Construit le contexte, score la transaction et génère les alertes."""
    ctx = {
        "amount": float(txn.amount),
        "channel": txn.channel.value,
        "source_system": txn.source_system.value,
    }
    if txn.counterparty_country:
        ctx["country"] = txn.counterparty_country
    if _detect_structuring(db, txn):
        ctx["pattern"] = "structuring"

    # Filtrage sanctions/PPE de l'émetteur et du bénéficiaire : alimente les
    # scénarios SANCTION_MATCH_* et PEP_HIT, exactement comme en KYC/KYS.
    parties = screen_parties(db, txn)
    if txn.tenant_id:
        # Le moteur de filtrage committe : on rétablit le contexte RLS avant
        # d'écrire l'évaluation et les alertes.
        from app.core.db import set_tenant_context
        set_tenant_context(db, str(txn.tenant_id))
    if parties:
        best = max(parties, key=lambda p: p["score"])
        ctx["match_score"] = best["score"]
        ctx["is_pep"] = any(p["is_pep"] for p in parties)
        ctx["matched_party"] = best["role"]
        ctx["matched_name"] = best["name"]

    # Libellé lisible : le CLIENT concerné en priorité (nom/prénom), pas un ID.
    label = (txn.customer_ref or "").strip() or (
        f"Opération {txn.external_ref}" if txn.external_ref else f"Opération {txn.amount} {txn.currency}"
    )
    assessment = scoring_service.score_subject(
        db,
        subject_type=SubjectType.TRANSACTION,
        context=ctx,
        subject_ref=txn.customer_ref or txn.external_ref,
        subject_label=label,
        tenant_id=txn.tenant_id,
        persist=True,
    )
    txn.risk_assessment_id = assessment.id
    db.commit()

    alerts = alerting_service.generate_from_assessment(
        db, assessment, source=alerting_service.AlertSource.KYT
    )

    # Trace des correspondances (nom rapproché, liste, programme) pour que la
    # Conformité voie POURQUOI l'opération est signalée.
    if alerts and parties:
        detail_screening = {
            "subject_label": ", ".join(f"{p['role']} : {p['name']}" for p in parties),
            "matches": [m for p in parties for m in p["matches"]],
            "parties": [
                {"role": p["role"], "name": p["name"], "score": p["score"], "is_pep": p["is_pep"]}
                for p in parties
            ],
        }
        for a in alerts:
            d = dict(a.detail or {})
            d["screening"] = detail_screening
            a.detail = d
        db.commit()

    return assessment, alerts


def ingest_transaction(db: Session, data: dict, tenant_id: Optional[UUID] = None):
    """Persiste une transaction puis l'analyse. Retourne (txn, assessment, alerts)."""
    txn = Transaction(tenant_id=tenant_id, **data)
    db.add(txn)
    db.commit()
    db.refresh(txn)
    assessment, alerts = analyze_transaction(db, txn)
    db.refresh(txn)
    return txn, assessment, alerts


def get_transaction_detail(db: Session, txn_id: UUID) -> Optional[dict]:
    """Une opération + son évaluation de risque (score, scénarios déclenchés)."""
    from app.models.scoring import RiskAssessment

    t = db.get(Transaction, txn_id)
    if not t:
        return None
    assessment = None
    if t.risk_assessment_id:
        a = db.get(RiskAssessment, t.risk_assessment_id)
        if a:
            assessment = {
                "total_score": a.total_score,
                "risk_class": a.risk_class.value if hasattr(a.risk_class, "value") else a.risk_class,
                "triggered": a.triggered or [],
                "context": a.context or {},
            }
    return {
        "id": str(t.id),
        "external_ref": t.external_ref,
        "source_system": t.source_system.value if hasattr(t.source_system, "value") else t.source_system,
        "direction": t.direction.value if hasattr(t.direction, "value") else t.direction,
        "channel": t.channel.value if hasattr(t.channel, "value") else t.channel,
        "amount": str(t.amount),
        "currency": t.currency,
        "customer_ref": t.customer_ref,
        "counterparty_name": t.counterparty_name,
        "counterparty_country": t.counterparty_country,
        "decision": getattr(t, "decision", None),
        "value_date": t.value_date.isoformat() if t.value_date else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "assessment": assessment,
        "events": alerting_service.list_events(db, subject_id=str(t.id)),
    }


def list_transactions(
    db: Session,
    customer_ref: Optional[str] = None,
    source_system: Optional[SourceSystem] = None,
    limit: int = 50,
) -> list[Transaction]:
    from app.models.scoring import RiskAssessment

    stmt = select(Transaction).order_by(Transaction.created_at.desc()).limit(limit)
    if customer_ref:
        stmt = stmt.where(Transaction.customer_ref == customer_ref)
    if source_system:
        stmt = stmt.where(Transaction.source_system == source_system)
    txns = list(db.execute(stmt).scalars().all())

    # Enrichit chaque opération avec son niveau de risque (évaluation liée).
    ids = [t.risk_assessment_id for t in txns if t.risk_assessment_id]
    classes: dict = {}
    if ids:
        for aid, rc in db.execute(
            select(RiskAssessment.id, RiskAssessment.risk_class).where(RiskAssessment.id.in_(ids))
        ).all():
            classes[aid] = rc.value if hasattr(rc, "value") else rc
    for t in txns:
        setattr(t, "risk_class", classes.get(t.risk_assessment_id))
    return txns


# --- Déclaration de soupçon (SAR) -------------------------------------------

def create_sar(db: Session, data: dict, created_by: Optional[UUID] = None,
               tenant_id: Optional[UUID] = None) -> SuspiciousActivityReport:
    sar = SuspiciousActivityReport(created_by=created_by, tenant_id=tenant_id, **data)
    db.add(sar)
    db.commit()
    db.refresh(sar)
    return sar


_SAR_TRANSITIONS = {
    SARStatus.DRAFT: {SARStatus.SUBMITTED},
    SARStatus.SUBMITTED: {SARStatus.UNDER_REVIEW},
    SARStatus.UNDER_REVIEW: {SARStatus.DECIDED},
    SARStatus.DECIDED: set(),
}


def update_sar(
    db: Session,
    sar_id: UUID,
    status: Optional[SARStatus] = None,
    decision: Optional[SARDecision] = None,
    reviewed_by: Optional[UUID] = None,
    narrative: Optional[str] = None,
) -> Optional[SuspiciousActivityReport]:
    sar = db.get(SuspiciousActivityReport, sar_id)
    if not sar:
        return None
    if status and status != sar.status:
        if status not in _SAR_TRANSITIONS.get(sar.status, set()):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=409,
                detail=f"Transition SAR {sar.status.value} → {status.value} non autorisée",
            )
        sar.status = status
    if decision:
        sar.decision = decision
    if narrative is not None:
        sar.narrative = narrative
    if reviewed_by:
        sar.reviewed_by = reviewed_by
    db.commit()
    db.refresh(sar)
    return sar


def list_sars(db: Session, status: Optional[SARStatus] = None, limit: int = 50):
    stmt = select(SuspiciousActivityReport).order_by(
        SuspiciousActivityReport.created_at.desc()
    ).limit(limit)
    if status:
        stmt = stmt.where(SuspiciousActivityReport.status == status)
    return list(db.execute(stmt).scalars().all())
