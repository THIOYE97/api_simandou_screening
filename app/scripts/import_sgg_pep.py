# app/scripts/import_sgg_pep.py
from __future__ import annotations

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


_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def clean_date(v: Any) -> Optional[str]:
    if not v:
        return None
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    m = _DATE_RE.match(s)
    if not m:
        return None
    return m.group(1)


# -----------------------------
# Sources table config (TON SCHÉMA)
# -----------------------------
DEFAULT_SOURCE_CODE = "SGG"
DEFAULT_SOURCE_NAME = "SGG PEP Lists"
DEFAULT_SOURCE_TYPE = "PEP_RULES"   # ✅ tu as confirmé que ça marche
DEFAULT_REFRESH_POLICY = "manual"   # requis (NOT NULL)


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    return []


def get_or_create_source_id(db: Session, source_code: str, source_name: str) -> int:
    sid = db.execute(
        text("SELECT id FROM sources WHERE source_code = :c LIMIT 1"),
        {"c": source_code},
    ).scalar_one_or_none()
    if sid is not None:
        return int(sid)

    # create
    db.execute(
        text(
            """
            INSERT INTO sources (source_code, source_name, source_type, refresh_policy, is_active)
            VALUES (:code, :name, CAST(:stype AS source_type), :policy, true)
            ON CONFLICT (source_code) DO NOTHING
            """
        ),
        {"code": source_code, "name": source_name, "stype": DEFAULT_SOURCE_TYPE, "policy": DEFAULT_REFRESH_POLICY},
    )
    db.commit()

    sid2 = db.execute(
        text("SELECT id FROM sources WHERE source_code = :c LIMIT 1"),
        {"c": source_code},
    ).scalar_one_or_none()
    if sid2 is None:
        raise RuntimeError(f"Source introuvable après insertion: {source_code}")
    return int(sid2)


def ensure_primary_name_row(db: Session, entity_id, primary_name: str) -> None:
    """
    S'assure qu'il existe au moins un EntityName PRIMARY pour cet entity.
    (utile si on veut mettre à jour le nom plus tard)
    """
    exists = db.execute(
        select(EntityName.entity_id).where(
            EntityName.entity_id == entity_id,
            EntityName.is_primary == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if exists:
        return

    n_raw = primary_name.strip()
    n_norm = normalize_name(n_raw)
    n_tokens = tokenize(n_norm)
    db.add(
        EntityName(
            entity_id=entity_id,
            name_raw=n_raw,
            name_normalized=n_norm,
            name_tokens=n_tokens,
            is_primary=True,
            name_type="PRIMARY",
        )
    )


def insert_new_pep(db: Session, source_id: int, source_ref: str, rec: dict[str, Any]) -> None:
    primary_name = (rec.get("primary_name") or rec.get("name") or "").strip()
    entity_type = (rec.get("entity_type") or "person").strip().lower()
    if entity_type not in ("person", "company"):
        entity_type = "person"

    country_focus = (rec.get("country_focus") or rec.get("country") or rec.get("nationality") or "").strip() or None
    risk_level = (rec.get("risk_level") or "MEDIUM").strip().upper()
    if risk_level not in ("LOW", "MEDIUM", "HIGH"):
        risk_level = "MEDIUM"

    entity_id = uuid.uuid4()
    db.add(
        Entity(
            id=entity_id,
            entity_type=entity_type,
            primary_name=primary_name.upper().strip(),
            country_focus=country_focus,
            risk_level=risk_level,
        )
    )

    def add_name(name_raw: str, name_type: str, is_primary: bool) -> None:
        n_raw = str(name_raw or "").strip()
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

    aliases = _as_list(rec.get("aliases"))
    if aliases:
        p_norm = normalize_name(primary_name)
        for a in aliases:
            a_norm = normalize_name(a)
            if a_norm and a_norm != p_norm:
                add_name(a, "ALIAS", False)

    program = (rec.get("program") or "PEP").strip()
    role = (rec.get("role") or rec.get("position") or "").strip()
    summary = (rec.get("summary") or "").strip()

    evidence_urls = rec.get("evidence_urls") or rec.get("urls") or None
    if isinstance(evidence_urls, str):
        evidence_urls = [evidence_urls]
    if evidence_urls is not None and not isinstance(evidence_urls, list):
        evidence_urls = None

    listed_on = clean_date(rec.get("listed_on") or rec.get("listed_date") or rec.get("date_listed"))
    unlisted_on = clean_date(rec.get("unlisted_on") or rec.get("delisted_on") or rec.get("date_unlisted"))

    raw_payload = dict(rec)
    if program and "program" not in raw_payload:
        raw_payload["program"] = program
    if role and "role" not in raw_payload:
        raw_payload["role"] = role

    sr_summary = None
    if role and summary:
        sr_summary = f"{role} — {summary}"
    elif role:
        sr_summary = role
    elif summary:
        sr_summary = summary

    db.add(
        SourceRecord(
            id=uuid.uuid4(),
            source_id=source_id,
            source_ref=source_ref,
            entity_id=entity_id,
            record_type="PEP",
            listed_on=listed_on,
            unlisted_on=unlisted_on,
            program=program if program else "PEP",
            summary=sr_summary,
            evidence_urls=evidence_urls,
            raw_payload=raw_payload,
        )
    )


def update_existing_pep(db: Session, sr: SourceRecord, rec: dict[str, Any]) -> None:
    """
    Update safe: on met à jour SourceRecord + raw_payload.
    (On ne change pas entity_id, pour éviter de casser les relations.)
    """
    program = (rec.get("program") or sr.program or "PEP").strip()
    role = (rec.get("role") or rec.get("position") or "").strip()
    summary = (rec.get("summary") or "").strip()

    evidence_urls = rec.get("evidence_urls") or rec.get("urls") or None
    if isinstance(evidence_urls, str):
        evidence_urls = [evidence_urls]
    if evidence_urls is not None and not isinstance(evidence_urls, list):
        evidence_urls = None

    listed_on = clean_date(rec.get("listed_on") or rec.get("listed_date") or rec.get("date_listed")) or sr.listed_on
    unlisted_on = clean_date(rec.get("unlisted_on") or rec.get("delisted_on") or rec.get("date_unlisted")) or sr.unlisted_on

    raw_payload = dict(rec)
    if program and "program" not in raw_payload:
        raw_payload["program"] = program
    if role and "role" not in raw_payload:
        raw_payload["role"] = role

    sr_summary = None
    if role and summary:
        sr_summary = f"{role} — {summary}"
    elif role:
        sr_summary = role
    elif summary:
        sr_summary = summary

    sr.program = program
    sr.summary = sr_summary
    sr.evidence_urls = evidence_urls
    sr.listed_on = listed_on
    sr.unlisted_on = unlisted_on
    sr.raw_payload = raw_payload

    # Optionnel: si on veut mettre à jour le nom affiché dans Entity (safe-ish)
    primary_name = (rec.get("primary_name") or rec.get("name") or "").strip()
    if primary_name:
        ent = db.execute(select(Entity).where(Entity.id == sr.entity_id)).scalar_one_or_none()
        if ent and ent.primary_name != primary_name.upper().strip():
            ent.primary_name = primary_name.upper().strip()
            ensure_primary_name_row(db, ent.id, primary_name)


def upsert_pep_record(db: Session, source_id: int, rec: dict[str, Any]) -> str:
    source_ref = (rec.get("source_ref") or rec.get("ref") or rec.get("source_reference") or "").strip()
    if not source_ref:
        return "bad"

    primary_name = (rec.get("primary_name") or rec.get("name") or "").strip()
    if not primary_name:
        return "bad"

    sr = db.execute(
        select(SourceRecord).where(
            SourceRecord.source_id == source_id,
            SourceRecord.source_ref == source_ref,
        )
    ).scalar_one_or_none()

    if sr:
        update_existing_pep(db, sr, rec)
        return "updated"

    insert_new_pep(db, source_id, source_ref, rec)
    return "inserted"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: PYTHONPATH=. python app/scripts/import_sgg_pep.py <file.jsonl> [SOURCE_CODE] [SOURCE_NAME]")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    source_code = sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_SOURCE_CODE
    source_name = sys.argv[3] if len(sys.argv) >= 4 else DEFAULT_SOURCE_NAME

    with SessionLocal() as db:
        source_id = get_or_create_source_id(db, source_code, source_name)
        print(f"[PEP] Using sources.id={source_id} for source_code={source_code}")

        inserted = 0
        updated = 0
        skipped = 0
        bad = 0

        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    res = upsert_pep_record(db, source_id, rec)
                    if res == "inserted":
                        inserted += 1
                    elif res == "updated":
                        updated += 1
                    elif res == "bad":
                        bad += 1
                    else:
                        skipped += 1

                    if (inserted + updated + skipped + bad) % 500 == 0:
                        db.commit()

                except Exception as e:
                    db.rollback()
                    bad += 1
                    print(f"[line {i}] ERROR: {e}")

        db.commit()

    print(f"Done. inserted={inserted}, updated={updated}, skipped={skipped}, bad={bad}")


if __name__ == "__main__":
    main()