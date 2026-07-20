"""
Adaptateurs de listes officielles : téléchargement + analyse.

Chaque adaptateur produit des enregistrements normalisés consommés par
`list_ingest.ingest`. Le format de chaque source a été établi sur le fichier
réel publié, pas supposé.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from typing import Iterator

import httpx

logger = logging.getLogger("simandou.list_adapters")

DOWNLOAD_TIMEOUT = 300.0


def _download_to_file(url: str) -> str:
    """
    Télécharge en FLUX vers un fichier temporaire.

    Les listes officielles pèsent plusieurs dizaines de Mo (47 Mo pour le
    Royaume-Uni). Les charger entièrement en mémoire faisait tomber l'instance
    (502). On écrit sur disque et on analyse en lecture séquentielle.
    """
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="sanctions_")
    os.close(fd)
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
    return path


# --------------------------------------------------------------------------
# Royaume-Uni — UK Sanctions List (FCDO)
# --------------------------------------------------------------------------
# ATTENTION : la liste consolidée OFSI a été FERMÉE le 28 janvier 2026 et n'est
# plus mise à jour. La UK Sanctions List publiée par le FCDO est désormais
# l'unique source des désignations britanniques.
#
# Particularités du fichier :
#   - une ligne de préambule « Report Date: ... » précède l'en-tête ;
#   - PLUSIEURS lignes par désignation, à regrouper par « Unique ID » ;
#   - pour une personne : Name 1..5 = prénoms, Name 6 = patronyme ;
#     pour une entité ou un navire : Name 6 = dénomination complète ;
#   - la casse de « Name type » est incohérente (Primary Name / Primary name /
#     Primary name variation) : il faut normaliser sous peine de perdre le nom
#     principal d'une partie des désignations.
UK_SANCTIONS_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
UK_SOURCE_CODE = "UK"
UK_SOURCE_NAME = "Sanctions — Royaume-Uni (UK Sanctions List)"

_NAME_COLS = [f"Name {i}" for i in range(1, 7)]


def _uk_full_name(row: dict) -> str:
    if (row.get("Designation Type") or "").strip().lower() == "individual":
        parts = [(row.get(c) or "").strip() for c in _NAME_COLS]
        return " ".join(p for p in parts if p)
    return (row.get("Name 6") or "").strip()


def fetch_uk_sanctions(url: str = UK_SANCTIONS_URL) -> Iterator[dict]:
    """Télécharge et regroupe la UK Sanctions List par désignation."""
    path = _download_to_file(url)
    grouped: dict[str, dict] = {}
    try:
        # Lecture LIGNE À LIGNE : matérialiser les 57 000 lignes en mémoire
        # coûtait plusieurs centaines de Mo. Seul le regroupement est conservé.
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            fh.readline()               # saute « Report Date: ... »
            for row in csv.DictReader(fh):
                _uk_accumulate(row, grouped)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    for entry in grouped.values():
        # Certaines désignations n'ont qu'une variation : elle devient le nom principal.
        if not entry["primary_name"]:
            if not entry["aliases"]:
                continue
            entry["primary_name"] = entry["aliases"].pop(0)
        entry.pop("_seen", None)
        yield entry


def _uk_accumulate(row: dict, grouped: dict[str, dict]) -> None:
    """Agrège une ligne dans la désignation à laquelle elle appartient."""
    uid = (row.get("Unique ID") or "").strip()
    name = _uk_full_name(row)
    if not uid or not name:
        return

    dtype = (row.get("Designation Type") or "").strip().lower()
    entity_type = "person" if dtype == "individual" else "company"
    is_primary = (row.get("Name type") or "").strip().lower() == "primary name"

    entry = grouped.setdefault(uid, {
            "source_ref": uid,
            "entity_type": entity_type,
            "primary_name": "",
            # Le fichier est dénormalisé sur les ADRESSES : le même nom
            # réapparaît sur des dizaines de lignes (jusqu'à 720 pour une seule
            # désignation). On dédoublonne en conservant l'ordre d'apparition,
            # sans quoi une entité se verrait attribuer des centaines d'alias
            # identiques.
            "_seen": {},
            "aliases": [],
            "program": (row.get("Regime Name") or "").strip() or None,
            "listed_on": None,
            "country": None,
            "summary": (row.get("UK Statement of Reasons") or "").strip()[:2000] or None,
            "raw": {"unique_id": uid, "designation_type": row.get("Designation Type"),
                    "source": row.get("Designation source"),
                    "sanctions": row.get("Sanctions Imposed")},
        })
    if name in entry["_seen"]:
        return
    entry["_seen"][name] = True
    if is_primary and not entry["primary_name"]:
        entry["primary_name"] = name
    elif name != entry["primary_name"]:
        entry["aliases"].append(name)


# --------------------------------------------------------------------------
# Canada — Loi sur les mesures économiques spéciales (SEMA)
# --------------------------------------------------------------------------
# Structure établie sur le fichier réel : 5 684 <record> à plat.
#   - personne : <LastName> + <GivenName> ;
#   - entité ou navire : <EntityOrShip> ;
#   - <Aliases> regroupe les alias en un seul texte ;
#   - <Country> porte le RÉGIME de sanction (« Belarus / Bélarus »), pas la
#     nationalité de la personne ;
#   - aucun identifiant unique : la clé stable est (Country, Schedule, Item),
#     vérifiée unique sur l'intégralité du fichier.
CANADA_URL = (
    "https://www.international.gc.ca/world-monde/assets/office_docs/"
    "international_relations-relations_internationales/sanctions/sema-lmes.xml"
)
CANADA_SOURCE_CODE = "CA"
CANADA_SOURCE_NAME = "Sanctions — Canada (LMES/SEMA)"


def _text(node, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _split_aliases(raw: str) -> list[str]:
    """Les alias sont dans un texte unique, séparés par « ; », « / » ou une virgule."""
    if not raw:
        return []
    parts = re.split(r"[;/]|,(?=\s*[A-ZÀ-Ý])", raw)
    return [p.strip() for p in parts if p and len(p.strip()) > 2]


def fetch_canada_sanctions(url: str = CANADA_URL) -> Iterator[dict]:
    """Télécharge et analyse la liste canadienne (LMES/SEMA)."""
    path = _download_to_file(url)
    try:
        for _, rec in ET.iterparse(path, events=("end",)):
            if rec.tag != "record":
                continue
            regime = _text(rec, "Country")
            entity = _text(rec, "EntityOrShip")
            last, given = _text(rec, "LastName"), _text(rec, "GivenName")

            if entity:
                name, etype = entity, "company"
            else:
                name = " ".join(p for p in (given, last) if p)
                etype = "person"
            if not name:
                rec.clear()
                continue

            ref = "|".join([regime, _text(rec, "Schedule"), _text(rec, "Item")])
            yield {
                "source_ref": ref,
                "entity_type": etype,
                "primary_name": name,
                "aliases": _split_aliases(_text(rec, "Aliases")),
                "program": regime or None,
                "listed_on": _text(rec, "DateOfListing") or None,
                "country": None,     # <Country> = régime, pas la nationalité
                "summary": None,
                "raw": {
                    "schedule": _text(rec, "Schedule"), "item": _text(rec, "Item"),
                    "dob": _text(rec, "DateOfBirthOrShipBuildDate"),
                    "imo": _text(rec, "ShipIMONumber"),
                },
            }
            rec.clear()          # libère la mémoire au fil de la lecture
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Registre des adaptateurs
# --------------------------------------------------------------------------
ADAPTERS: dict[str, dict] = {
    UK_SOURCE_CODE: {
        "name": UK_SOURCE_NAME,
        "fetch": fetch_uk_sanctions,
        "record_type": "SANCTION",
        "url": UK_SANCTIONS_URL,
        "label": "Royaume-Uni — UK Sanctions List (FCDO)",
    },
    CANADA_SOURCE_CODE: {
        "name": CANADA_SOURCE_NAME,
        "fetch": fetch_canada_sanctions,
        "record_type": "SANCTION",
        "url": CANADA_URL,
        "label": "Canada — Mesures économiques spéciales (LMES)",
    },
}
