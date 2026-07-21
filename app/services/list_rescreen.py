"""
Re-filtrage du portefeuille après mise à jour d'une liste.

Exigence explicite du TDR (§VII, module Identification des personnes
suspectes) : le profilage doit être systématique « à réception d'une nouvelle
liste ou d'une liste mise à jour ». Sans cela, un client déjà en relation qui
apparaît demain sur une liste OFAC ne déclenche rien — le dispositif ne
détecte que les nouveaux entrants.

Le sens de parcours est important : on part des entités NOUVELLEMENT inscrites
et on cherche les sujets connus qui leur ressemblent, et non l'inverse. Les
inscriptions nouvelles se comptent en dizaines quand le portefeuille se compte
en milliers.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("simandou.list_rescreen")

# Seuil de rapprochement. Volontairement élevé : une alerte de re-filtrage
# tombe sans qu'un analyste l'ait demandée, et une avalanche de faux positifs
# ferait perdre confiance au dispositif tout entier.
RESCREEN_THRESHOLD = 0.72

RULE_CODE = "LIST_UPDATE_HIT"


def rescreen_for_entities(
    db: Session,
    entity_ids: Iterable[str],
    *,
    source_code: Optional[str] = None,
    threshold: float = RESCREEN_THRESHOLD,
) -> dict:
    """
    Confronte les sujets déjà vérifiés aux entités nouvellement inscrites.

    Retourne le nombre d'alertes créées. Ne lève pas : un échec de re-filtrage
    ne doit pas invalider une mise à jour de liste réussie.
    """
    ids = [str(e) for e in entity_ids if e]
    if not ids:
        return {"candidates": 0, "alerts": 0}

    # Sujets déjà vérifiés, dédoublonnés par nom normalisé. On garde le
    # libellé le plus récent pour que l'alerte soit lisible.
    subjects = db.execute(text("""
        SELECT DISTINCT ON (norm)
               norm,
               COALESCE(request_payload->>'name', norm) AS label,
               tenant_id::text AS tenant_id
          FROM (
              SELECT request_payload,
                     tenant_id,
                     UPPER(TRIM(COALESCE(request_payload->>'name_normalized',
                                         request_payload->>'name', ''))) AS norm,
                     created_at
                FROM screening_requests
          ) s
         WHERE norm <> '' AND LENGTH(norm) >= 4
         ORDER BY norm, created_at DESC
    """)).mappings().all()

    if not subjects:
        return {"candidates": 0, "alerts": 0}

    # Table temporaire indexée : sans elle, comparer chaque nouvelle
    # inscription à chaque sujet serait un produit cartésien.
    db.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _rescreen_subjects (
            norm text PRIMARY KEY, label text, tenant_id text
        ) ON COMMIT DROP
    """))
    db.execute(text("TRUNCATE _rescreen_subjects"))
    db.execute(text("""
        INSERT INTO _rescreen_subjects (norm, label, tenant_id)
        VALUES (:norm, :label, :tenant_id) ON CONFLICT (norm) DO NOTHING
    """), [dict(s) for s in subjects])
    db.execute(text("CREATE INDEX ON _rescreen_subjects USING gin (norm gin_trgm_ops)"))
    db.execute(text("ANALYZE _rescreen_subjects"))
    # « SET LOCAL » n'accepte pas de paramètre lié : on passe par set_config,
    # qui en accepte un — et le troisième argument le limite à la transaction.
    db.execute(text("SELECT set_config('pg_trgm.similarity_threshold', :t, true)"),
               {"t": str(threshold)})

    hits = db.execute(text("""
        SELECT s.norm, s.label, s.tenant_id,
               e.id::text AS entity_id, e.primary_name, e.risk_level::text AS risk_level,
               MAX(similarity(en.name_normalized, s.norm)) AS sim
          FROM entity_names en
          JOIN entities e ON e.id = en.entity_id
          JOIN _rescreen_subjects s ON en.name_normalized % s.norm
         WHERE e.id = ANY(CAST(:ids AS uuid[]))
         GROUP BY s.norm, s.label, s.tenant_id, e.id, e.primary_name, e.risk_level
         ORDER BY sim DESC
    """), {"ids": ids}).mappings().all()

    created = 0
    for h in hits:
        # Idempotence : relancer une mise à jour ne doit pas empiler les
        # alertes pour un même couple sujet / entité.
        exists = db.execute(text("""
            SELECT 1 FROM alerts
             WHERE rule_code = :rc
               AND subject_ref = :sr
               AND detail->>'entity_id' = :eid
             LIMIT 1
        """), {"rc": RULE_CODE, "sr": h["norm"], "eid": h["entity_id"]}).first()
        if exists:
            continue

        score = int(round(float(h["sim"] or 0) * 100))
        severity = "CRITICAL" if score >= 90 else "HIGH"
        db.execute(text("""
            INSERT INTO alerts
                (id, tenant_id, source, severity, status, title, rule_code,
                 subject_ref, subject_label, detail)
            VALUES (gen_random_uuid(),
                    CAST(NULLIF(:tid, '') AS uuid),
                    'SCREENING', CAST(:sev AS alert_severity), 'OPEN',
                    :title, :rc, :sr, :label, CAST(:detail AS jsonb))
        """), {
            "tid": h["tenant_id"] or "",
            "sev": severity,
            "title": f"Inscription nouvelle sur liste : {h['primary_name']}",
            "rc": RULE_CODE,
            "sr": h["norm"],
            "label": h["label"],
            "detail": _json({
                "reason": "Un sujet déjà vérifié ressemble à une personne "
                          "nouvellement inscrite sur une liste.",
                "entity_id": h["entity_id"],
                "listed_name": h["primary_name"],
                "entity_risk": h["risk_level"],
                "score": score,
                "source": source_code,
                "trigger": "LIST_UPDATE",
            }),
        })
        created += 1

    db.commit()
    logger.info("list_rescreen_done",
                extra={"result": {"source": source_code, "candidates": len(hits),
                                  "alerts": created}})
    return {"candidates": len(hits), "alerts": created}


def _json(d: dict) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)
