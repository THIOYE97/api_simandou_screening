"""
Liste noire et interdits bancaires propres à la BCRG.

TDR §VII — Module Identification des personnes suspectes, sous-module Liste
noire ; et §VI — « la prise en charge des Listes Internationales, Nationales
ainsi que d'éventuelles listes propres à la BCRG ».

Ce ne sont PAS des sanctions internationales : une interdiction bancaire est
une mesure nationale, prononcée par la Banque Centrale, généralement à la
suite d'incidents de paiement. Elle est donc rangée sous « avis officiel » et
non sous « sanction » — la distinction compte dans un dossier, où l'analyste
doit savoir s'il a devant lui une désignation de l'ONU ou une décision
guinéenne.

Le rapprochement lui-même n'a rien de spécifique : ces personnes rejoignent
l'index de filtrage commun, si bien qu'une vérification KYC les détecte au
même titre qu'une cible sanctionnée, sans code dédié.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import list_ingest, list_refresh

logger = logging.getLogger("simandou.blacklist")

SOURCE_CODE = "BCRG_INTERDITS"
SOURCE_NAME = "Guinée — BCRG, liste noire et interdits bancaires"
# Une interdiction bancaire est un acte officiel national, pas une sanction
# internationale : le type le dit, et l'affichage en dépend.
SOURCE_TYPE = "OFFICIAL_NOTICE"
RECORD_TYPE = "NOTICE"

CSV_COLONNES = ("reference", "nom", "type", "motif", "date_decision", "pays")

# Motifs usuels d'une interdiction bancaire, à titre indicatif : le champ reste
# libre, la BCRG restant maîtresse de sa nomenclature.
MOTIFS_COURANTS = (
    "Incidents de paiement",
    "Chèques sans provision",
    "Interdiction judiciaire",
    "Décision administrative",
    "Fraude documentaire",
)


def modele_csv() -> str:
    lignes = [
        ",".join(CSV_COLONNES),
        "BCRG-2026-001,MAMADOU DIALLO,person,Chèques sans provision,2026-03-14,GN",
        "BCRG-2026-002,SOCIETE EXEMPLE SARL,company,Incidents de paiement,2026-04-02,GN",
        "BCRG-2026-003,AMINATA BAH,person,Interdiction judiciaire,2026-05-20,GN",
    ]
    return "\n".join(lignes) + "\n"


def _lire_csv(contenu: bytes) -> Iterator[dict]:
    """
    Convertit le fichier de la BCRG au format du moteur d'ingestion.

    La référence de la décision porte l'identité de l'enregistrement : c'est
    elle qui permet de reverser une liste corrigée sans créer de doublon, et de
    lever une interdiction en la retirant du fichier.
    """
    try:
        texte = contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = contenu.decode("latin-1", errors="replace")

    lecteur = csv.DictReader(io.StringIO(texte))
    entetes = [(c or "").strip().lower() for c in (lecteur.fieldnames or [])]
    if "nom" not in entetes or "reference" not in entetes:
        raise ValueError(
            "Colonnes « reference » et « nom » obligatoires. Attendu : "
            + ", ".join(CSV_COLONNES)
        )

    for ligne in lecteur:
        d = {(k or "").strip().lower(): (v or "").strip()
             for k, v in ligne.items() if k}
        nom, ref = d.get("nom", ""), d.get("reference", "")
        if not nom or not ref:
            continue
        brut = (d.get("type") or "").lower()
        yield {
            "source_ref": ref,
            "primary_name": nom,
            "entity_type": "company" if brut.startswith(("c", "m", "s")) else "person",
            "country": d.get("pays") or "GN",
            "aliases": [],
            "program": d.get("motif") or None,
            "listed_on": d.get("date_decision") or None,
            "summary": (f"Interdiction bancaire — {d.get('motif')}"
                        if d.get("motif") else "Interdiction bancaire"),
            "raw": {"reference": ref, "motif": d.get("motif")},
        }


def importer(db: Session, contenu: bytes, dry_run: bool = False) -> dict:
    """
    Reverse la liste de la BCRG.

    On passe par le moteur de rafraîchissement commun, et non par une simple
    insertion : c'est lui qui sait fusionner sans dupliquer, et surtout RADIER
    les références absentes du nouveau fichier. Une interdiction levée doit
    cesser de produire des correspondances — sans quoi la levée resterait sans
    effet, exactement le défaut qui affectait les listes internationales.
    """
    lignes = list(_lire_csv(contenu))
    if not lignes:
        raise ValueError("Aucune ligne exploitable dans le fichier.")

    return list_refresh.refresh_source(
        db,
        source_code=SOURCE_CODE,
        source_name=SOURCE_NAME,
        records=iter(lignes),
        record_type=RECORD_TYPE,
        risk_level="HIGH",
        source_type=SOURCE_TYPE,
        # La BCRG reverse SA liste : elle fait autorité sur son contenu. Un
        # écart de volume n'y est pas le signe d'un flux tronqué mais d'une
        # décision — le garde-fou de couverture, conçu pour les flux externes,
        # rendrait ici toute levée d'interdiction sans effet.
        #
        # Le risque se déplace donc sur l'opérateur : un fichier incomplet
        # lèverait des interdictions à tort. C'est pourquoi l'import expose une
        # simulation, et que l'écran fait confirmer dès qu'une levée est en jeu.
        force=True,
        min_coverage=0.0,
        dry_run=dry_run,
    )


def etat(db: Session) -> dict:
    """Volumétrie de la liste, pour l'écran de gestion."""
    src = db.execute(text("SELECT id FROM sources WHERE source_code = :c"),
                     {"c": SOURCE_CODE}).scalar()
    if not src:
        return {"source_id": None, "actifs": 0, "leves": 0, "total": 0}
    r = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE unlisted_on IS NULL) AS actifs,
               COUNT(*) FILTER (WHERE unlisted_on IS NOT NULL) AS leves,
               COUNT(*) AS total
          FROM source_records WHERE source_id = :s
    """), {"s": src}).mappings().first()
    return {"source_id": src, **dict(r)}


def lister(db: Session, limit: int = 500) -> list[dict]:
    src = db.execute(text("SELECT id FROM sources WHERE source_code = :c"),
                     {"c": SOURCE_CODE}).scalar()
    if not src:
        return []
    rows = db.execute(text("""
        SELECT sr.source_ref, e.primary_name, e.entity_type::text AS entity_type,
               sr.program AS motif, sr.listed_on::text AS date_decision,
               sr.unlisted_on::text AS date_levee
          FROM source_records sr
          JOIN entities e ON e.id = sr.entity_id
         WHERE sr.source_id = :s
         ORDER BY sr.unlisted_on NULLS FIRST, e.primary_name
         LIMIT :lim
    """), {"s": src, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]
