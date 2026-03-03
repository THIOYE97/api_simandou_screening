import json
import sys
import uuid
import re
from pathlib import Path
from typing import Any, Optional
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.screening_db import Entity, EntityName, SourceRecord
from app.services.matching import normalize_name, tokenize


# ====== CONFIG ======
OFAC_SOURCE_CODE = "OFAC"
OFAC_SOURCE_NAME = "US Treasury OFAC SDN"
OFAC_SOURCE_ID = 2           # adapte si besoin (dans ta table sources)
RECORD_TYPE = "SANCTION"
DEFAULT_RISK = "HIGH"

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def clean_date(v: Any) -> Optional[str]:
    """Retourne 'YYYY-MM-DD' ou None. Gère aussi '2015-07-01-04:00'."""
    if not v:
        return None
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    m = _DATE_RE.match(s)
    return m.group(1) if m else None


def ensure_ofac_source(db: Session) -> None:
    """
    Optionnel: tente de créer/assurer la présence de la source OFAC dans la table sources.
    On ignore si ta table sources n'a pas les colonnes attendues.
    """
    try:
        db.execute(
            text("""
            INSERT INTO sources (id, source_code, source_name, source_type, refresh_policy, is_active)
            VALUES (:id, :code, :name, 'SANCTIONS', 'manual', true)
            ON CONFLICT (id) DO NOTHING
            """),
            {"id": OFAC_SOURCE_ID, "code": OFAC_SOURCE_CODE, "name": OFAC_SOURCE_NAME},
        )
        db.commit()
    except Exception:
        db.rollback()
        # ta table sources peut ne pas matcher -> on ignore
        pass


def guess_entity_type(rec: dict[str, Any]) -> str:
    """
    DB enum entity_type = person/company.
    Heuristique simple basée sur la présence de dob + mots clés sociétés.
    """
    if rec.get("dob"):
        return "person"

    name = (rec.get("primary_name") or "").upper()
    if any(x in name for x in ["LTD", "LIMITED", "INC", "SA", "SARL", "GMBH", "LLC", "CO.", "COMPANY", "AIRLINES", "BANK"]):
        return "company"

    # OFAC SDN contient souvent des entités, mais par défaut on met company si pas de dob
    return "company"


def upsert_ofac_record(db: Session, rec: dict[str, Any]) -> bool:
    """
    Insère l'entité + noms + source_record si (source_id, source_ref) n'existe pas.
    Retourne True si inséré, False si skip.
    """
    source_ref = rec.get("source_ref")
    if not source_ref:
        return False

    # si déjà importé
    existing = db.execute(
        select(SourceRecord.id).where(
            SourceRecord.source_id == OFAC_SOURCE_ID,
            SourceRecord.source_ref == str(source_ref),
        )
    ).scalar_one_or_none()
    if existing:
        return False

    primary_name = (rec.get("primary_name") or "").strip()
    if not primary_name:
        return False

    entity_type = guess_entity_type(rec)
    country_focus = None
    # si tu veux une logique: prendre 1ère nationalité
    nats = rec.get("nationalities")
    if isinstance(nats, list) and nats:
        country_focus = str(nats[0]).strip() or None

    risk_level = DEFAULT_RISK
    entity_id = uuid.uuid4()

    # 1) entity
    ent = Entity(
        id=entity_id,
        entity_type=entity_type,
        primary_name=primary_name.upper().strip(),
        country_focus=country_focus,
        risk_level=risk_level,
    )
    db.add(ent)

    # 2) entity_names
    def add_name(name_raw: str, name_type: str, is_primary: bool):
        name_raw = str(name_raw).strip()
        if not name_raw:
            return
        n_norm = normalize_name(name_raw)
        db.add(
            EntityName(
                entity_id=entity_id,
                name_raw=name_raw,
                name_normalized=n_norm,
                name_tokens=tokenize(n_norm),
                is_primary=is_primary,
                name_type=name_type,
            )
        )

    add_name(primary_name, "PRIMARY", True)

    aliases = rec.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    if isinstance(aliases, list):
        for a in aliases:
            if not a:
                continue
            a = str(a).strip()
            if not a:
                continue
            if normalize_name(a) == normalize_name(primary_name):
                continue
            add_name(a, "ALIAS", False)

    # 3) source_record
    program = rec.get("program")
    summary = rec.get("summary")
    evidence_urls = rec.get("evidence_urls")
    if isinstance(evidence_urls, str):
        evidence_urls = [evidence_urls]
    if evidence_urls is not None and not isinstance(evidence_urls, list):
        evidence_urls = None

    listed_on = clean_date(rec.get("listed_on"))
    unlisted_on = clean_date(rec.get("unlisted_on"))

    sr = SourceRecord(
        id=uuid.uuid4(),
        source_id=OFAC_SOURCE_ID,
        source_ref=str(source_ref),
        entity_id=entity_id,
        record_type=RECORD_TYPE,
        listed_on=listed_on,
        unlisted_on=unlisted_on,
        program=program,
        summary=summary,
        evidence_urls=evidence_urls,
        raw_payload=rec.get("raw_payload") or rec,
    )
    db.add(sr)

    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: PYTHONPATH=. python app/scripts/import_ofac_sdn.py data/ofac_sdn.jsonl")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    with SessionLocal() as db:
        ensure_ofac_source(db)

        inserted = 0
        skipped = 0
        bad = 0

        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    rec = json.loads(line)
                    ok = upsert_ofac_record(db, rec)

                    if ok:
                        inserted += 1
                    else:
                        skipped += 1

                    if (inserted + skipped) % 500 == 0:
                        db.commit()

                except Exception as e:
                    db.rollback()
                    bad += 1
                    print(f"[line {i}] ERROR: {e}")

        db.commit()

    print(f"OFAC import done → inserted={inserted}, skipped={skipped}, bad={bad}")


if __name__ == "__main__":
    main()
