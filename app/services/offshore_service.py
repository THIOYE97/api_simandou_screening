"""
Fuites offshore (ICIJ) — chargement et consultation.

Base tenue à l'écart de l'index de filtrage. On ne la parcourt pas à chaque
vérification : l'analyste l'interroge quand il enquête sur un dossier.

Source : International Consortium of Investigative Journalists (ICIJ),
Offshore Leaks Database — Offshore Leaks, Panama Papers, Bahamas Leaks,
Paradise Papers, Pandora Papers. Données sous licence à réciprocité
(ODbL / CC-BY-SA) ; l'attribution à l'ICIJ est obligatoire à l'affichage.

Les données s'arrêtent en 2020 : une correspondance signale une structure ayant
EXISTÉ, jamais une situation actuelle — et figurer dans ces fuites n'est pas
un délit.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from typing import Iterator, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.matching import normalize_name

logger = logging.getLogger("simandou.offshore")

ICIJ_URL = "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
ICIJ_ATTRIBUTION = (
    "Source : International Consortium of Investigative Journalists (ICIJ), "
    "Offshore Leaks Database — données jusqu'à 2020."
)

# Fichier de l'archive et champs utiles, par nature d'enregistrement.
_MEMBERS = {
    "OFFICER": "nodes-officers.csv",
    "ENTITY": "nodes-entities.csv",
    "INTERMEDIARY": "nodes-intermediaries.csv",
}

BATCH = 1000


def parse_icij(path: str, kind: str, offset: int = 0, limit: int = 5000) -> Iterator[dict]:
    """
    Lit une tranche d'un fichier de l'archive, SANS la décompresser entièrement.

    L'archive fait 70 Mo compressés pour 626 Mo décompressés : une extraction
    complète saturerait le disque de l'instance. `zipfile` permet de lire un
    membre en flux, et l'on saute jusqu'au décalage demandé.
    """
    member = _MEMBERS.get(kind.upper())
    if not member:
        raise ValueError(f"Nature inconnue : {kind}")

    with zipfile.ZipFile(path) as z:
        with z.open(member) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
            produced = 0
            for i, row in enumerate(reader):
                if i < offset:
                    continue
                if produced >= limit:
                    return
                name = (row.get("name") or "").strip()
                node_id = (row.get("node_id") or "").strip()
                if not name or not node_id:
                    continue
                produced += 1
                yield {
                    "node_id": node_id,
                    "kind": kind.upper(),
                    "name": name,
                    "name_normalized": normalize_name(name),
                    "countries": (row.get("countries") or "").strip()[:255] or None,
                    "country_codes": (row.get("country_codes") or "").strip()[:128] or None,
                    "jurisdiction": (row.get("jurisdiction_description")
                                     or row.get("jurisdiction") or "").strip()[:128] or None,
                    "investigation": (row.get("sourceID") or "").strip()[:128] or None,
                    "incorporation_date": (row.get("incorporation_date") or "").strip()[:32] or None,
                    "status": (row.get("status") or "").strip()[:64] or None,
                    "note": (row.get("note") or "").strip()[:500] or None,
                    "raw": {"service_provider": row.get("service_provider"),
                            "address": (row.get("address") or "")[:300]},
                }


def ingest(db: Session, records: Iterator[dict]) -> dict[str, int]:
    """Insère une tranche. Idempotent : (node_id, kind) déjà présent est ignoré."""
    created = skipped = read = 0
    pending: list[dict] = []

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        db.execute(text("""
            INSERT INTO offshore_records
                (node_id, kind, name, name_normalized, countries, country_codes,
                 jurisdiction, investigation, incorporation_date, status, note, raw)
            VALUES (:node_id, CAST(:kind AS offshore_kind), :name, :name_normalized,
                    :countries, :country_codes, :jurisdiction, :investigation,
                    :incorporation_date, :status, :note, CAST(:raw AS jsonb))
            ON CONFLICT (node_id, kind) DO NOTHING
        """), pending)
        db.commit()
        pending = []

    # L'idempotence est déléguée à la base (ON CONFLICT) : charger les
    # identifiants existants en mémoire coûterait des centaines de Mo sur
    # 1,6 million de lignes.
    for rec in records:
        read += 1
        rec = dict(rec)
        rec["raw"] = json.dumps(rec.get("raw") or {}, ensure_ascii=False)
        pending.append(rec)
        created += 1
        if len(pending) >= BATCH:
            flush()
    flush()
    # « created » compte les lignes PRÉSENTÉES ; les doublons sont écartés
    # silencieusement par la contrainte d'unicité.
    return {"presented": created, "skipped": skipped, "read": read}


def search(db: Session, query: str, limit: int = 30, kind: Optional[str] = None) -> list[dict]:
    """
    Recherche par ressemblance. Les graphies varient fortement dans ces corpus
    (translittérations, abréviations) : une égalité stricte ne trouverait rien.
    """
    q = normalize_name(query or "")
    if len(q) < 3:
        return []
    # L'opérateur « % » de pg_trgm est le SEUL à exploiter l'index GIN ;
    # « similarity(...) > seuil » dans le WHERE impose un balayage complet.
    # Le seuil se règle donc par variable de session, pas dans la condition.
    # Pas de doublement du « % » : psycopg3 lie les paramètres côté serveur
    # ($1) et transmet la requête telle quelle, sans interpolation.
    db.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.35"))
    sql = """
        SELECT node_id, kind::text AS kind, name, countries, jurisdiction,
               investigation, incorporation_date, status,
               ROUND((similarity(name_normalized, :q) * 100)::numeric) AS score
        FROM offshore_records
        WHERE name_normalized % :q
    """
    params: dict = {"q": q, "lim": limit}
    if kind:
        sql += " AND kind = CAST(:kind AS offshore_kind)"
        params["kind"] = kind.upper()
    sql += " ORDER BY score DESC, name LIMIT :lim"
    rows = db.execute(text(sql), params).mappings().all()
    return [dict(r) | {"score": int(r["score"])} for r in rows]


def stats(db: Session) -> dict:
    rows = db.execute(text(
        "SELECT kind::text AS kind, COUNT(*)::int AS n FROM offshore_records GROUP BY kind"
    )).mappings().all()
    by_kind = {r["kind"]: r["n"] for r in rows}
    return {"total": sum(by_kind.values()), "by_kind": by_kind,
            "attribution": ICIJ_ATTRIBUTION}
