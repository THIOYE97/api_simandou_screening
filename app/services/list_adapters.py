"""
Adaptateurs de listes officielles : téléchargement + analyse.

Chaque adaptateur produit des enregistrements normalisés consommés par
`list_ingest.ingest`. Le format de chaque source a été établi sur le fichier
réel publié, pas supposé.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Iterator

import httpx

logger = logging.getLogger("simandou.list_adapters")

DOWNLOAD_TIMEOUT = 300.0


def _download_text(url: str) -> str:
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content.decode("utf-8-sig", errors="replace")


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
    raw = _download_text(url)
    buf = io.StringIO(raw)
    buf.readline()                      # saute « Report Date: ... »
    reader = csv.DictReader(buf)

    grouped: dict[str, dict] = {}
    for row in reader:
        uid = (row.get("Unique ID") or "").strip()
        name = _uk_full_name(row)
        if not uid or not name:
            continue

        dtype = (row.get("Designation Type") or "").strip().lower()
        entity_type = "person" if dtype == "individual" else "company"
        ntype = (row.get("Name type") or "").strip().lower()
        is_primary = ntype == "primary name"

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
            continue
        entry["_seen"][name] = True
        if is_primary and not entry["primary_name"]:
            entry["primary_name"] = name
        elif name != entry["primary_name"]:
            entry["aliases"].append(name)

    for entry in grouped.values():
        # Certaines désignations n'ont qu'une variation : elle devient le nom principal.
        if not entry["primary_name"]:
            if not entry["aliases"]:
                continue
            entry["primary_name"] = entry["aliases"].pop(0)
        entry.pop("_seen", None)
        yield entry


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
}
