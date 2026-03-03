import json
import sys
import uuid
from pathlib import Path
from typing import Any, Optional
import re
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.screening_db import Entity, EntityName, SourceRecord
from app.services.matching import normalize_name, tokenize


# --- Date cleaning: accepte "YYYY-MM-DD", "YYYY-MM-DD-04:00", "YYYY-MM-DDT00:00:00Z", etc.
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def clean_date(v: Any) -> Optional[str]:
    """
    Retourne une string 'YYYY-MM-DD' (Postgres la caste en DATE),
    ou None si non parsable.
    """
    if not v:
        return None
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    m = _DATE_RE.match(s)
    if not m:
        return None
    return m.group(1)


UN_SOURCE_CODE = "UN"
UN_SOURCE_NAME = "United Nations Sanctions"
UN_SOURCE_ID = 1  # adapte si ton "sources.id" pour UN est différent


def guess_entity_type(rec: dict[str, Any]) -> str:
    # DB enum entity_type = person/company
    if rec.get("dob") or rec.get("date_of_birth") or rec.get("birth_date"):
        return "person"

    name = (rec.get("primary_name") or "").upper()
    if any(x in name for x in ["LTD", "LIMITED", "INC", "SA", "SARL", "GMBH", "LLC", "CO.", "COMPANY"]):
        return "company"
    return "person"


def ensure_un_source(db: Session) -> None:
    """
    Optionnel: crée/assure la ligne UN dans table sources si elle existe et match (id, code, name).
    Si ta table sources a un autre schéma, ça rollback et on ignore.
    """
    try:
        db.execute(
            text("""
            INSERT INTO sources (id, code, name)
            VALUES (:id, :code, :name)
            ON CONFLICT (id) DO NOTHING
            """),
            {"id": UN_SOURCE_ID, "code": UN_SOURCE_CODE, "name": UN_SOURCE_NAME},
        )
        db.commit()
    except Exception:
        db.rollback()
        pass


def upsert_un_record(db: Session, rec: dict[str, Any]) -> bool:
    """
    Retourne True si inséré, False si déjà existant / ignoré.
    """
    source_ref = rec.get("source_ref") or rec.get("source_reference") or rec.get("ref")
    if not source_ref:
        return False

    # déjà importé ?
    existing = db.execute(
        select(SourceRecord.id).where(
            SourceRecord.source_id == UN_SOURCE_ID,
            SourceRecord.source_ref == str(source_ref),
        )
    ).scalar_one_or_none()
    if existing:
        return False

    primary_name = (rec.get("primary_name") or "").strip()
    if not primary_name:
        return False

    entity_type = guess_entity_type(rec)
    country_focus = rec.get("country") or rec.get("nationality") or rec.get("country_focus")

    # UN sanctions => HIGH
    risk_level = "HIGH"

    entity_id = uuid.uuid4()

    # entity
    ent = Entity(
        id=entity_id,
        entity_type=entity_type,
        primary_name=primary_name.upper().strip(),
        country_focus=country_focus,
        risk_level=risk_level,
    )
    db.add(ent)

    # entity_names
    def add_name(name_raw: str, name_type: str, is_primary: bool) -> None:
        n_raw = str(name_raw).strip()
        if not n_raw:
            return
        n_norm = normalize_name(n_raw)
        n_tokens = tokenize(n_norm)
        db.add(
            EntityName(
                entity_id=entity_id,
                name_raw=n_raw,
                name_normalized=n_norm,
                name_tokens=n_tokens,
                is_primary=is_primary,
                name_type=name_type,
            )
        )

    add_name(primary_name, "PRIMARY", True)

    aliases = rec.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    if isinstance(aliases, list):
        p_norm = normalize_name(primary_name)
        for a in aliases:
            if not a:
                continue
            a = str(a).strip()
            if a and normalize_name(a) != p_norm:
                add_name(a, "ALIAS", False)

    # source_record fields
    program = rec.get("program") or rec.get("sanctions_program") or rec.get("listed_under")
    summary = rec.get("summary") or rec.get("comment") or rec.get("remarks")

    evidence_urls = rec.get("evidence_urls") or rec.get("urls") or None
    if isinstance(evidence_urls, str):
        evidence_urls = [evidence_urls]
    if evidence_urls is not None and not isinstance(evidence_urls, list):
        evidence_urls = None

    listed_on = clean_date(rec.get("listed_on") or rec.get("listed_date") or rec.get("date_listed"))
    unlisted_on = clean_date(rec.get("unlisted_on") or rec.get("delisted_on") or rec.get("date_unlisted"))

    sr = SourceRecord(
        id=uuid.uuid4(),
        source_id=UN_SOURCE_ID,
        source_ref=str(source_ref),
        entity_id=entity_id,
        record_type="SANCTION",
        listed_on=listed_on,
        unlisted_on=unlisted_on,
        program=program,
        summary=summary,
        evidence_urls=evidence_urls,
        raw_payload=rec,
    )
    db.add(sr)

    return True


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: PYTHONPATH=. python app/scripts/import_un_sanctions.py data/un_sanctions.jsonl")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    with SessionLocal() as db:
        ensure_un_source(db)

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
                    ok = upsert_un_record(db, rec)
                    if ok:
                        inserted += 1
                    else:
                        skipped += 1

                    # commit batch
                    if (inserted + skipped) % 500 == 0:
                        db.commit()

                except Exception as e:
                    db.rollback()
                    bad += 1
                    print(f"[line {i}] ERROR: {e}")

        db.commit()

    print(f"Done. inserted={inserted}, skipped={skipped}, bad={bad}")


if __name__ == "__main__":
    main()
