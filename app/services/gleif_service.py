"""
Détention capitalistique d'une société — référentiel GLEIF (LEI).

Complète le registre INTERNE de bénéficiaires effectifs, sans le remplacer :
ce sont deux choses distinctes qu'il ne faut jamais confondre.

  - le registre interne recense ce que l'ASSUJETTI a déclaré à la BCRG, pièces
    à l'appui, et va jusqu'à la personne physique ;
  - GLEIF publie la détention entre PERSONNES MORALES (maison mère directe et
    ultime au sens comptable). Il ne nomme jamais la personne physique finale.

Interrogé À LA DEMANDE, sans copie locale : le référentiel compte plus de deux
millions d'entités, et l'intérêt n'est pas de les filtrer mais de savoir qui
détient une société précise.

Licence : les données GLEIF sont publiées en CC0 (domaine public), sans
inscription ni clé d'accès — c'est ce qui la rend intégrable sans réserve dans
un produit livré à une banque centrale.

Limite assumée : le niveau 2 (relations) est SPARSE. Beaucoup d'entités
invoquent une exception de déclaration — notamment les entreprises d'État.
L'absence de maison mère ne signifie donc pas l'absence de détenteur.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("simandou.gleif")

GLEIF_API = "https://api.gleif.org/api/v1"
TIMEOUT = 20.0
_HEADERS = {"Accept": "application/vnd.api+json"}


def _get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS, follow_redirects=True) as c:
            r = c.get(f"{GLEIF_API}/{path}", params=params)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
    except Exception:
        logger.exception("gleif_request_failed", extra={"path": path})
        return None


def _entity_out(record: dict) -> dict[str, Any]:
    attrs = record.get("attributes") or {}
    entity = attrs.get("entity") or {}
    reg = attrs.get("registration") or {}
    return {
        "lei": record.get("id"),
        "name": ((entity.get("legalName") or {}).get("name")),
        "country": (entity.get("legalAddress") or {}).get("country"),
        "jurisdiction": entity.get("jurisdiction"),
        "status": entity.get("status"),
        "registration_status": reg.get("status"),
    }


def find_entity(name: str) -> Optional[dict]:
    """Retrouve une société par sa dénomination exacte."""
    if not name or len(name.strip()) < 3:
        return None
    data = _get("lei-records", {"filter[entity.legalName]": name.strip(), "page[size]": 1})
    records = (data or {}).get("data") or []
    return _entity_out(records[0]) if records else None


def _related(lei: str, relation: str) -> Optional[dict]:
    data = _get(f"lei-records/{lei}/{relation}")
    payload = (data or {}).get("data")
    if not payload:
        return None
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    return _entity_out(payload) if payload else None


def ownership(name: str) -> dict[str, Any]:
    """
    Détention capitalistique connue d'une société.

    Retourne toujours une réponse exploitable : « non trouvée » et « trouvée
    sans détenteur déclaré » sont deux informations différentes, et l'analyste
    doit pouvoir les distinguer — la seconde n'autorise pas à conclure que la
    société n'a pas de détenteur.
    """
    entity = find_entity(name)
    if not entity:
        return {"found": False, "entity": None, "direct_parent": None,
                "ultimate_parent": None, "children_count": 0,
                "note": "Aucune société de ce nom au référentiel LEI."}

    lei = entity["lei"]
    direct = _related(lei, "direct-parent")
    ultimate = _related(lei, "ultimate-parent")

    children = _get(f"lei-records/{lei}/direct-children", {"page[size]": 1})
    n_children = ((children or {}).get("meta") or {}).get("pagination", {}).get("total", 0)

    note = None
    if not direct and not ultimate:
        note = ("Société identifiée, mais aucune maison mère déclarée au "
                "référentiel LEI. Cela ne signifie pas qu'elle n'a pas de "
                "détenteur : la déclaration de niveau 2 admet des exceptions, "
                "fréquemment invoquées par les entreprises d'État.")

    return {
        "found": True,
        "entity": entity,
        "direct_parent": direct,
        "ultimate_parent": ultimate,
        "children_count": int(n_children or 0),
        "note": note,
    }
