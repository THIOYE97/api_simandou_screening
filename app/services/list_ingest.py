"""
Ingestion générique d'une liste de surveillance.

Un adaptateur (par source) produit des enregistrements NORMALISÉS ; ce module
s'occupe seul de l'écriture en base (source, entité, noms, enregistrement) et
de l'idempotence. Ajouter une liste revient donc à écrire un analyseur, pas un
script d'import complet — c'est ce qui rend l'ajout de nouvelles sources
raisonnable.

Enregistrement normalisé attendu :
    {
      "source_ref":   str,                  # identifiant stable dans la source
      "entity_type":  "person" | "company",
      "primary_name": str,
      "aliases":      list[str],
      "program":      str | None,           # régime / programme de sanction
      "listed_on":    str | None,           # AAAA-MM-JJ
      "country":      str | None,
      "summary":      str | None,
      "raw":          dict,
    }
"""
from __future__ import annotations

import logging
import uuid
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.matching import normalize_name, tokenize

logger = logging.getLogger("simandou.list_ingest")

BATCH = 500


def get_or_create_source(
    db: Session, *, code: str, name: str,
    source_type: str = "SANCTIONS", refresh_policy: str = "MANUAL",
) -> int:
    """Retourne l'identifiant de la source, en la créant au besoin."""
    sid = db.execute(
        text("SELECT id FROM sources WHERE source_code = :c LIMIT 1"), {"c": code}
    ).scalar()
    if sid:
        # Le libellé peut avoir été affiné entre deux versions.
        db.execute(
            text("UPDATE sources SET source_name = :n WHERE id = :i AND source_name IS DISTINCT FROM :n"),
            {"n": name, "i": sid},
        )
        db.commit()
        return int(sid)
    db.execute(
        text("""
            INSERT INTO sources (source_code, source_name, source_type, refresh_policy, is_active)
            VALUES (:c, :n, :t, :p, true)
            ON CONFLICT (source_code) DO NOTHING
        """),
        {"c": code, "n": name, "t": source_type, "p": refresh_policy},
    )
    db.commit()
    sid = db.execute(
        text("SELECT id FROM sources WHERE source_code = :c LIMIT 1"), {"c": code}
    ).scalar()
    if not sid:
        raise RuntimeError(f"Source introuvable après création : {code}")
    return int(sid)


def _existing_refs(db: Session, source_id: int) -> set[str]:
    rows = db.execute(
        text("SELECT source_ref FROM source_records WHERE source_id = :s"), {"s": source_id}
    ).scalars().all()
    return {str(r) for r in rows if r}


def ingest(
    db: Session,
    *,
    source_code: str,
    source_name: str,
    records: Iterable[dict],
    record_type: str = "SANCTION",
    risk_level: str = "HIGH",
    evidence_url: Optional[str] = None,
    source_type: str = "SANCTIONS",
    max_records: Optional[int] = None,
) -> dict[str, int]:
    """
    Écrit les enregistrements et retourne le compte (créés / ignorés).

    Idempotent : un `source_ref` déjà présent pour cette source est ignoré, ce
    qui permet de relancer une mise à jour sans dupliquer.

    `max_records` plafonne le nombre de CRÉATIONS par appel : les listes
    volumineuses s'importent ainsi par tranches successives sans dépasser le
    délai d'une requête HTTP, chaque appel reprenant là où le précédent s'est
    arrêté. `remaining` indique s'il reste du travail.
    """
    source_id = get_or_create_source(db, code=source_code, name=source_name, source_type=source_type)
    seen = _existing_refs(db, source_id)
    created = skipped = read = 0

    for rec in records:
        read += 1
        ref = str(rec.get("source_ref") or "").strip()
        primary = (rec.get("primary_name") or "").strip()
        if not ref or not primary:
            skipped += 1
            continue
        if ref in seen:
            skipped += 1
            continue
        seen.add(ref)

        entity_id = uuid.uuid4()
        db.execute(
            text("""
                INSERT INTO entities (id, entity_type, primary_name, country_focus, risk_level)
                VALUES (:i, :t, :n, :c, :r)
            """),
            {"i": str(entity_id), "t": rec.get("entity_type") or "person",
             "n": primary.upper(), "c": rec.get("country"), "r": risk_level},
        )

        def _add_name(value: str, is_primary: bool) -> None:
            value = (value or "").strip()
            if not value:
                return
            norm = normalize_name(value)
            db.execute(
                text("""
                    INSERT INTO entity_names
                        (entity_id, name_raw, name_normalized, name_tokens, is_primary, name_type)
                    VALUES (:e, :raw, :norm, :tok, :prim, :typ)
                """),
                {"e": str(entity_id), "raw": value, "norm": norm, "tok": tokenize(norm),
                 "prim": is_primary, "typ": "PRIMARY" if is_primary else "ALIAS"},
            )

        _add_name(primary, True)
        pnorm = normalize_name(primary)
        for alias in dict.fromkeys(rec.get("aliases") or []):     # dédoublonne en gardant l'ordre
            if alias and normalize_name(alias) != pnorm:
                _add_name(alias, False)

        db.execute(
            text("""
                INSERT INTO source_records
                    (id, source_id, source_ref, entity_id, record_type, listed_on,
                     program, summary, evidence_urls, raw_payload)
                VALUES (:i, :s, :ref, :e, :rt, :listed, :prog, :sum, :ev, CAST(:raw AS jsonb))
            """),
            {"i": str(uuid.uuid4()), "s": source_id, "ref": ref, "e": str(entity_id),
             "rt": record_type, "listed": rec.get("listed_on"), "prog": rec.get("program"),
             "sum": rec.get("summary"),
             "ev": [evidence_url] if evidence_url else [],
             "raw": __import__("json").dumps(rec.get("raw") or {}, ensure_ascii=False)},
        )

        created += 1
        if max_records and created >= max_records:
            db.commit()
            return {"created": created, "skipped": skipped, "read": read,
                    "source_id": source_id, "remaining": True}
        if created % BATCH == 0:
            db.commit()
            # NB : « created » est un attribut RÉSERVÉ de LogRecord (horodatage).
            # L'employer comme clé de `extra` fait lever un KeyError par logging.
            logger.info("list_ingest_progress",
                        extra={"source": source_code, "records_created": created})

    db.commit()
    return {"created": created, "skipped": skipped, "read": read,
            "source_id": source_id, "remaining": False}
