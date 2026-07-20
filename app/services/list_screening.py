"""
Filtrage d'un nom contre les listes (sanctions, PPE, adverse media).

Point d'entrée COMMUN au KYC/KYS, au KYT et aux bénéficiaires effectifs : tous
doivent interroger le même moteur et les mêmes listes.

Il encapsule surtout une subtilité qui a déjà provoqué des pannes silencieuses :
le moteur exige le contexte tenant (`app.tenant_id`) pour la RLS, et il committe
en interne — ce qui rend la connexion au pool et perd le contexte. Sans le
rétablir AVANT le filtrage puis AVANT la relecture des correspondances, on
obtient soit une erreur, soit — bien pire — zéro correspondance sans erreur.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("simandou.screening")

_MATCH_SQL = text("""
    SELECT sm.match_score, sm.match_band, sm.reasons,
           e.primary_name AS entity_name,
           COALESCE(s.source_name, e.source_name) AS source_name,
           sr.program, sr.record_type
    FROM screening_matches sm
    LEFT JOIN entities e ON e.id = sm.entity_id
    LEFT JOIN source_records sr ON sr.id = sm.source_record_id
    LEFT JOIN sources s ON s.id = sr.source_id
    WHERE sm.request_id = CAST(:rid AS uuid)
    ORDER BY sm.match_score DESC
    LIMIT 10
""")


def is_screenable(name: Optional[str]) -> bool:
    """Écarte les identifiants et noms trop courts pour un rapprochement fiable."""
    clean = (name or "").strip()
    return len(clean) >= 4 and len(clean.split()) >= 2


def screen_name(
    db: Session,
    *,
    name: str,
    tenant_id: Optional[UUID] = None,
    trigger: str = "list_screening",
    country: Optional[str] = None,
    extra_meta: Optional[dict] = None,
) -> Optional[dict]:
    """
    Confronte un nom aux listes. Retourne None si le filtrage a échoué
    (l'appelant décide alors s'il poursuit) ; sinon un résultat, éventuellement
    sans correspondance — « vérifié, rien trouvé » est une information.
    """
    from app.core.db import set_tenant_context
    from app.services.simple_screening_engine import run_simple_screening

    meta = {"trigger": trigger, **(extra_meta or {})}
    try:
        if tenant_id:
            set_tenant_context(db, str(tenant_id))
        res = run_simple_screening(db=db, name=name.strip(), country_focus=country, meta=meta)
        # Le moteur a committé : on repose le contexte avant de relire.
        if tenant_id:
            set_tenant_context(db, str(tenant_id))
        rows = db.execute(_MATCH_SQL, {"rid": str(res["request_id"])}).mappings().all()
    except Exception:
        logger.exception("list_screening_failed", extra={"trigger": trigger})
        return None

    return {
        "name": name.strip(),
        "request_id": str(res["request_id"]),
        "score": int(rows[0]["match_score"] or 0) if rows else 0,
        "is_pep": any(str(r["record_type"] or "").upper() == "PEP" for r in rows),
        "matches": [
            {
                "name": r["entity_name"], "source": r["source_name"], "program": r["program"],
                "record_type": r["record_type"], "score": int(r["match_score"] or 0),
                "band": r["match_band"],
            }
            for r in rows
        ],
    }
