import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.screening_db import Entity, EntityName, SourceRecord
from app.services.matching import normalize_name, tokenize

EU_SOURCE_ID = 3
RECORD_TYPE = "SANCTION"
DEFAULT_RISK = "HIGH"

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def clean_date(v: Optional[str]):
    if not v:
        return None
    s = str(v).strip()
    m = _DATE_RE.match(s)
    return m.group(1) if m else None


def alias_to_name(n: ET.Element) -> Optional[str]:
    wn = (n.attrib.get("wholeName") or "").strip()
    if wn:
        return wn
    parts = [
        (n.attrib.get("firstName") or "").strip(),
        (n.attrib.get("middleName") or "").strip(),
        (n.attrib.get("lastName") or "").strip(),
    ]
    full = " ".join([p for p in parts if p]).strip()
    return full or None


def upsert_entity(
    db: Session,
    source_ref: str,
    entity_type: str,
    primary_name: str,
    aliases: list[str],
    programme: Optional[str],
    listed_on: Optional[str],
    raw_payload: dict,
) -> bool:
    # skip if already imported
    exists = db.execute(
        select(SourceRecord.id).where(
            SourceRecord.source_id == EU_SOURCE_ID,
            SourceRecord.source_ref == source_ref,
        )
    ).scalar_one_or_none()

    if exists:
        return False

    entity_id = uuid.uuid4()

    ent = Entity(
        id=entity_id,
        entity_type=entity_type,   # "person" / "company"
        primary_name=primary_name, # déjà en UPPER
        country_focus=None,
        risk_level=DEFAULT_RISK,   # "HIGH"
    )
    db.add(ent)

    def add_name(name: str, is_primary: bool):
        name = name.strip()
        if not name:
            return
        norm = normalize_name(name)
        db.add(
            EntityName(
                entity_id=entity_id,
                name_raw=name,
                name_normalized=norm,
                name_tokens=tokenize(norm),
                is_primary=is_primary,
                name_type="PRIMARY" if is_primary else "ALIAS",
            )
        )

    add_name(primary_name, True)

    # add aliases (dedup vs primary)
    p_norm = normalize_name(primary_name)
    for a in aliases:
        if not a:
            continue
        if normalize_name(a) != p_norm:
            add_name(a, False)

    sr = SourceRecord(
        id=uuid.uuid4(),
        source_id=EU_SOURCE_ID,
        source_ref=source_ref,
        entity_id=entity_id,
        record_type=RECORD_TYPE,
        listed_on=clean_date(listed_on),
        unlisted_on=None,
        program=programme,
        summary=None,
        evidence_urls=["https://data.europa.eu"],
        raw_payload=raw_payload,
    )
    db.add(sr)

    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: PYTHONPATH=. python app/scripts/import_eu_sanctions.py data/eu_consolidated.xml")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    tree = ET.parse(path)
    root = tree.getroot()

    # namespace extraction (ex: {http://eu.europa.eu/...})
    ns_uri = root.tag.split("}")[0].strip("{")
    ns = {"eu": ns_uri}

    rows = root.findall(".//eu:sanctionEntity", ns)

    inserted = 0
    skipped = 0
    bad = 0

    with SessionLocal() as db:
        for i, r in enumerate(rows, start=1):
            try:
                source_ref = r.attrib.get("euReferenceNumber") or ""
                logical_id = r.attrib.get("logicalId")

                if not source_ref:
                    skipped += 1
                    continue

                subject = r.find("eu:subjectType", ns)
                subject_code = subject.attrib.get("code") if subject is not None else None
                entity_type = "person" if subject_code == "person" else "company"

                names = r.findall("eu:nameAlias", ns)
                if not names:
                    skipped += 1
                    continue

                all_names: list[str] = []
                for n in names:
                    nm = alias_to_name(n)
                    if nm:
                        all_names.append(nm.upper())

                if not all_names:
                    skipped += 1
                    continue

                primary_name = all_names[0]
                other_aliases = all_names[1:]

                # regulation est souvent sous regulationSummary
                regulation = r.find(".//eu:regulation", ns)
                programme = regulation.attrib.get("programme") if regulation is not None else None
                listed_on = regulation.attrib.get("publicationDate") if regulation is not None else None

                ok = upsert_entity(
                    db=db,
                    source_ref=source_ref,
                    entity_type=entity_type,
                    primary_name=primary_name,
                    aliases=other_aliases,
                    programme=programme,
                    listed_on=listed_on,
                    raw_payload={
                        "source": "EU",
                        "euReferenceNumber": source_ref,
                        "logicalId": logical_id,
                        "names": all_names,
                        "programme": programme,
                        "listed_on": listed_on,
                    },
                )

                if ok:
                    inserted += 1
                else:
                    skipped += 1

                if (inserted + skipped) % 500 == 0:
                    db.commit()

            except Exception as e:
                db.rollback()
                bad += 1
                print(f"[entity {i}] ERROR: {e}")

        db.commit()

    print(f"EU import done → inserted={inserted}, skipped={skipped}, bad={bad}")


if __name__ == "__main__":
    main()
