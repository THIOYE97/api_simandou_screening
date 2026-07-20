"""
Regroupement inter-sources des correspondances.

Une même personne est désignée par plusieurs autorités : Loukachenko figure à la
fois sur les listes de l'ONU, de l'UE, de l'OFAC, du Royaume-Uni et du SECO.
Chaque source produit sa propre entité, donc l'analyste voyait cinq lignes
identiques — et le phénomène s'aggrave à chaque liste ajoutée.

Choix de conception : on regroupe à l'AFFICHAGE, sans fusionner les entités en
base. Deux raisons :

1. Fusionner des homonymes réellement distincts serait une erreur irréversible,
   et rien ne distingue de façon fiable deux personnes portant le même nom.
2. La traçabilité « quelle autorité a désigné qui » doit être conservée : c'est
   elle qui est vérifiée en inspection et qui fonde une décision de blocage.

Les enregistrements sources restent donc intacts et consultables ; seul le
regroupement est calculé à la volée.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable


def normalize_key(value: Any) -> str:
    """
    Clé de regroupement : majuscules, sans accents ni ponctuation, et
    INSENSIBLE À L'ORDRE des composantes du nom.

    Les autorités n'écrivent pas les noms dans le même ordre : l'OFAC publie
    « DZMITRY ALIAKSANDRAVICH LUKASHENKA » là où le SECO écrit « Lukashenka
    Dzmitry Aliaksandravich ». Sans tri des composantes, la même personne
    formait deux groupes distincts — le défaut même qu'on cherche à corriger.
    """
    txt = unicodedata.normalize("NFD", str(value or ""))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = re.sub(r"[^A-Za-z0-9]+", " ", txt).strip().upper()
    return " ".join(sorted(t for t in txt.split() if t))


def group_matches(matches: Iterable[dict]) -> list[dict]:
    """
    Regroupe les correspondances par personne (nom normalisé).

    Retourne une liste triée par score décroissant. Chaque groupe porte le
    meilleur score obtenu et la liste des autorités qui ont désigné la personne
    — c'est cette énumération qui a une valeur de conformité : une personne
    listée par cinq autorités n'est pas au même niveau de risque qu'une
    personne listée par une seule.
    """
    groups: dict[str, dict] = {}

    for m in matches:
        name = m.get("entity_name") or m.get("name") or ""
        key = normalize_key(name)
        if not key:
            continue

        score = int(m.get("match_score") or m.get("score") or 0)
        src_code = m.get("source_code") or m.get("source") or None
        src_name = m.get("source_name") or None
        program = m.get("program") or None
        rec_type = m.get("record_type") or None

        g = groups.setdefault(key, {
            "name": name,
            "score": score,
            "band": m.get("match_band") or m.get("band"),
            "sources": [],
            "_source_keys": set(),
            "programs": [],
            "record_types": [],
            "match_count": 0,
            "match_ids": [],
            "is_pep": False,
        })

        if score > g["score"]:
            g["score"] = score
            g["band"] = m.get("match_band") or m.get("band")
            g["name"] = name          # on retient la graphie la mieux notée

        src_key = src_code or src_name
        if src_key and src_key not in g["_source_keys"]:
            g["_source_keys"].add(src_key)
            g["sources"].append({"code": src_code, "name": src_name})
        if program and program not in g["programs"]:
            g["programs"].append(program)
        if rec_type and rec_type not in g["record_types"]:
            g["record_types"].append(rec_type)
        if str(rec_type or "").upper() == "PEP":
            g["is_pep"] = True

        g["match_count"] += 1
        if m.get("id") is not None:
            g["match_ids"].append(m["id"])

    out = []
    for g in groups.values():
        g.pop("_source_keys", None)
        g["source_count"] = len(g["sources"])
        out.append(g)
    return sorted(out, key=lambda g: (-g["score"], g["name"]))
