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
import time
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
    invalidate_stats_cache()
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


# Dénombrement mis en cache. Compter 1,6 million de lignes coûte 5 à 8 s :
# Postgres n'a pas de compteur de lignes, il doit toutes les parcourir. Or ce
# décompte est appelé à chaque ouverture de l'écran et ne bouge qu'à l'import.
_STATS_TTL_S = 900
_stats_cache: dict = {"at": 0.0, "value": None}


def invalidate_stats_cache() -> None:
    _stats_cache["value"] = None


def stats(db: Session) -> dict:
    now = time.monotonic()
    cached = _stats_cache["value"]
    if cached is not None and (now - _stats_cache["at"]) < _STATS_TTL_S:
        return cached
    rows = db.execute(text(
        "SELECT kind::text AS kind, COUNT(*)::int AS n FROM offshore_records GROUP BY kind"
    )).mappings().all()
    by_kind = {r["kind"]: r["n"] for r in rows}
    value = {"total": sum(by_kind.values()), "by_kind": by_kind,
             "attribution": ICIJ_ATTRIBUTION}
    _stats_cache.update(at=now, value=value)
    return value


# ─── Liens entre acteurs (relations ICIJ) ─────────────────────────────────────

REL_MEMBER = "relationships.csv"

# L'ICIJ emploie 716 libellés de rôle distincts. Les ramener à quatre classes
# est ce qui rend l'information lisible dans un dossier : un « ultimate
# beneficial owner » et un « auditor of » ne se traitent pas de la même façon.
#
# Le classement est volontairement PRUDENT : n'est tenu pour détention que ce
# qui l'exprime sans ambiguïté. Un rôle inconnu tombe dans OTHER plutôt que
# d'être promu bénéficiaire par excès de zèle — annoncer à tort un
# bénéficiaire effectif est plus grave que de n'en annoncer aucun.
_ROLE_OWNER = (
    "ultimate beneficial owner", "beneficial owner", "beneficiary",
    # Notion britannique de bénéficiaire effectif : elle relève bien de la
    # détention, et non d'un simple mandat.
    "person of significant control",
    "owner of", "owner", "settlor", "trustee", "protector",
)
_ROLE_SHARE = ("shareholder", "sole shareholder", "member of", "partner",
               "subscriber")
_ROLE_MGMT = (
    "director", "secretary", "president", "vice-president", "chairman",
    "treasurer", "manager", "managing director", "legal representative",
    "judicial representative", "signatory", "proxy", "attorney",
    "liquidator", "auditor", "records & registers", "officer",
    "representative", "custodian", "administrator", "nominee",
)


def classify_role(raw: str) -> str:
    """Ramène un libellé de rôle ICIJ à une classe exploitable."""
    r = (raw or "").strip().lower()
    if not r:
        return "OTHER"
    # L'ordre compte : « ultimate beneficial owner » contient « owner », et
    # doit être reconnu comme détention avant tout autre essai.
    for needle in _ROLE_OWNER:
        if needle in r:
            return "BENEFICIAL_OWNER"
    for needle in _ROLE_SHARE:
        if needle in r:
            return "SHAREHOLDER"
    for needle in _ROLE_MGMT:
        if needle in r:
            return "MANAGEMENT"
    return "OTHER"


def parse_relations(path: str, offset: int = 0, limit: int = 50000) -> Iterator[dict]:
    """
    Lit une tranche des arêtes, en ne retenant que les liens « officer_of ».

    Les adresses partagées et les homonymies ne disent rien d'une détention et
    représenteraient un million de lignes de bruit.
    """
    with zipfile.ZipFile(path) as z:
        with z.open(REL_MEMBER) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
            seen = produced = 0
            for row in reader:
                if (row.get("rel_type") or "").strip() != "officer_of":
                    continue
                seen += 1
                if seen <= offset:
                    continue
                if produced >= limit:
                    return
                start = (row.get("node_id_start") or "").strip()
                end = (row.get("node_id_end") or "").strip()
                if not start or not end:
                    continue
                produced += 1
                raw = (row.get("link") or "").strip()[:160]
                yield {
                    "node_id_start": start,
                    "node_id_end": end,
                    "rel_type": "officer_of",
                    "role_raw": raw or None,
                    "role_class": classify_role(raw),
                    "source": (row.get("sourceID") or "").strip()[:128] or None,
                }


def ingest_relations(db: Session, records: Iterator[dict]) -> dict[str, int]:
    read = 0
    pending: list[dict] = []

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        db.execute(text("""
            INSERT INTO offshore_relations
                (node_id_start, node_id_end, rel_type, role_raw, role_class, source)
            VALUES (:node_id_start, :node_id_end, :rel_type, :role_raw, :role_class, :source)
            ON CONFLICT (node_id_start, node_id_end, rel_type, role_raw) DO NOTHING
        """), pending)
        db.commit()
        pending = []

    for rec in records:
        read += 1
        pending.append(rec)
        if len(pending) >= BATCH:
            flush()
    flush()
    return {"read": read}


# Ordre d'affichage : ce qui exprime une détention passe avant une fonction.
_ROLE_RANK = {"BENEFICIAL_OWNER": 0, "SHAREHOLDER": 1, "MANAGEMENT": 2, "OTHER": 3}
_ROLE_LABEL = {
    "BENEFICIAL_OWNER": "Bénéficiaire effectif déclaré",
    "SHAREHOLDER": "Actionnaire",
    "MANAGEMENT": "Dirigeant / mandataire",
    "OTHER": "Autre rôle",
}


def linked_parties(db: Session, name: str, subject_is_company: bool,
                   limit: int = 40) -> dict:
    """
    Acteurs rattachés à un sujet dans les fuites offshore.

    Pour une personne morale : ceux qui la détiennent ou la dirigent.
    Pour une personne physique : les sociétés qui lui sont rattachées.

    Ce sont des rattachements POTENTIELS. Les données s'arrêtent en 2020, un
    rapprochement se fait sur le nom, et l'ICIJ n'est pas un registre de
    bénéficiaires effectifs : rien ici n'établit une détention.
    """
    q = normalize_name(name or "")
    if len(q) < 3:
        return {"subject_found": False, "subject": None, "parties": []}

    db.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.55"))
    # Une personne ne peut être qu'un OFFICER. Une société, elle, apparaît
    # SOIT comme société offshore (ENTITY), SOIT comme actionnaire d'une autre
    # société — et l'ICIJ l'enregistre alors comme OFFICER. Restreindre les
    # sociétés aux seuls ENTITY faisait manquer tous les actionnaires
    # personnes morales : « Petróleos de Venezuela » n'était pas retrouvé.
    kinds = ["ENTITY", "OFFICER", "INTERMEDIARY"] if subject_is_company else ["OFFICER"]
    subj = db.execute(text("""
        SELECT node_id, name, kind::text AS kind, jurisdiction, investigation,
               incorporation_date, status,
               ROUND((similarity(name_normalized, :q) * 100)::numeric) AS score,
               -- À ressemblance égale, une société est d'abord une société.
               CASE WHEN kind = 'ENTITY' THEN 0 ELSE 1 END AS rang
          FROM offshore_records
         WHERE kind = ANY(CAST(:k AS offshore_kind[])) AND name_normalized % :q
         ORDER BY score DESC, rang, name
         LIMIT 1
    """), {"q": q, "k": kinds}).mappings().first()
    if not subj:
        return {"subject_found": False, "subject": None, "parties": []}

    # Le sens de lecture découle de la nature du nœud TROUVÉ, pas de celle du
    # sujet : l'arête va toujours de l'acteur vers la société détenue. Un nœud
    # ENTITY se lit donc « qui me détient », tout autre « que dois-je détenir ».
    if subj["kind"] == "ENTITY":
        sql = """
            SELECT r.role_raw, r.role_class, r.source,
                   o.node_id, o.name, o.countries, o.jurisdiction, o.kind::text AS kind
              FROM offshore_relations r
              JOIN offshore_records o
                ON o.node_id = r.node_id_start AND o.kind <> 'ENTITY'
             WHERE r.node_id_end = :nid
        """
    else:
        sql = """
            SELECT r.role_raw, r.role_class, r.source,
                   o.node_id, o.name, o.countries, o.jurisdiction, o.kind::text AS kind
              FROM offshore_relations r
              JOIN offshore_records o
                ON o.node_id = r.node_id_end AND o.kind = 'ENTITY'
             WHERE r.node_id_start = :nid
        """
    rows = db.execute(text(sql + " LIMIT :lim"),
                      {"nid": subj["node_id"], "lim": limit}).mappings().all()

    parties = sorted(
        ({**dict(r), "role_label": _ROLE_LABEL.get(r["role_class"], "Autre rôle")}
         for r in rows),
        key=lambda p: (_ROLE_RANK.get(p["role_class"], 9), p["name"] or ""),
    )
    return {
        "subject_found": True,
        "subject": {**dict(subj), "score": int(subj["score"])},
        "parties": parties,
        "attribution": ICIJ_ATTRIBUTION,
    }
