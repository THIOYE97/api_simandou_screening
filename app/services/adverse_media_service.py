"""
Service métier — Adverse media.

Screening d'un nom candidat contre la base adverse media, via le moteur de
matching flou existant (normalize_name / tokenize / score_candidate).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.adverse_media import AdverseMediaCategory, AdverseMediaRecord
from app.services.matching import normalize_name, score_candidate, tokenize

logger = logging.getLogger("simandou.adverse_media")

MATCH_THRESHOLD = 65  # POSSIBLE ou mieux
# Au-delà, le rapprochement est tenu pour probable : lui seul peut porter
# le dossier en risque élevé quand le fait signalé est grave.
STRONG_MATCH_SCORE = 85

# Catégories tenues pour graves : elles portent le risque à HIGH, les autres
# à MEDIUM. Un signalement de blanchiment n'a pas le même poids qu'un litige
# commercial rangé dans « OTHER ».
_SEVERE = {
    AdverseMediaCategory.MONEY_LAUNDERING.value,
    AdverseMediaCategory.TERRORISM.value,
    AdverseMediaCategory.SANCTIONS_EVASION.value,
    AdverseMediaCategory.ORGANIZED_CRIME.value,
    AdverseMediaCategory.TRAFFICKING.value,
}


def _trigrams(norm: str) -> set[str]:
    s = norm.replace(" ", "")
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


# Formes juridiques : « LIMITED » et « LTD » désignent la même chose, mais leur
# écriture diffère assez pour faire tomber le score sous le seuil (mesuré à 61
# contre 65 requis). On les ramène à une écriture unique AVANT de comparer.
# On canonise plutôt qu'on ne supprime : effacer la forme rendrait
# « ATLAS TRADING SA » et « ATLAS TRADING LTD » identiques, alors que ce sont
# deux entités distinctes.
_LEGAL_FORMS = {
    "LIMITED": "LTD", "LTD": "LTD", "LIMITEE": "LTD",
    "INCORPORATED": "INC", "INC": "INC",
    "CORPORATION": "CORP", "CORP": "CORP",
    "COMPANY": "CO", "CO": "CO",
    "SOCIETE ANONYME": "SA", "SA": "SA",
    "SOCIETE A RESPONSABILITE LIMITEE": "SARL", "SARL": "SARL",
    "ENTREPRISE UNIPERSONNELLE A RESPONSABILITE LIMITEE": "EURL", "EURL": "EURL",
    "SOCIETE PAR ACTIONS SIMPLIFIEE": "SAS", "SAS": "SAS",
    "PUBLIC LIMITED COMPANY": "PLC", "PLC": "PLC",
    "AKTIENGESELLSCHAFT": "AG", "AG": "AG",
    "NAAMLOZE VENNOOTSCHAP": "NV", "NV": "NV",
    "BESLOTEN VENNOOTSCHAP": "BV", "BV": "BV",
    "GMBH": "GMBH", "SPA": "SPA", "GIE": "GIE", "SUARL": "SUARL",
}
# Les formes en plusieurs mots d'abord : « SOCIETE ANONYME » doit être traité
# avant que « SA » ne soit cherché parmi les jetons isolés.
_MULTIWORD_FORMS = sorted((f for f in _LEGAL_FORMS if " " in f), key=len, reverse=True)


def canonical_company(norm: str) -> str:
    """Ramène les formes juridiques d'une dénomination à une écriture unique."""
    out = norm
    for phrase in _MULTIWORD_FORMS:
        if phrase in out:
            out = out.replace(phrase, _LEGAL_FORMS[phrase])
    return " ".join(_LEGAL_FORMS.get(t, t) for t in out.split())


def _similarity(a_norm: str, b_norm: str) -> int:
    ta, tb = _trigrams(a_norm), _trigrams(b_norm)
    trig = (len(ta & tb) / len(ta | tb)) if (ta or tb) else 0.0
    sa, sb = set(tokenize(a_norm)), set(tokenize(b_norm))
    tok = (len(sa & sb) / max(len(sa), len(sb))) if (sa or sb) else 0.0
    return score_candidate(trig, tok)


def screen_name(db: Session, name: str, threshold: int = MATCH_THRESHOLD) -> list[dict]:
    """Retourne les enregistrements adverse media proches du nom, triés par score."""
    target = normalize_name(name)
    if len(target) < 3:
        return []
    # Pré-filtrage par l'index trigramme : sans lui, chaque vérification
    # chargerait toute la base en mémoire pour la parcourir en Python.
    # Le seuil est volontairement plus bas que MATCH_THRESHOLD — il ne fait que
    # restreindre les candidats, le score final restant calculé ci-dessous.
    db.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.3"))
    ids = db.execute(text("""
        SELECT id FROM adverse_media_records
        WHERE active IS TRUE AND normalized_name % :q
        LIMIT 500
    """), {"q": target}).scalars().all()
    if not ids:
        return []
    records = db.execute(
        select(AdverseMediaRecord).where(AdverseMediaRecord.id.in_(ids))
    ).scalars().all()

    out: list[dict] = []
    target_canon = canonical_company(target)
    for r in records:
        # On retient la meilleure des deux lectures : brute, et formes
        # juridiques canonisées. Canoniser ne doit jamais dégrader un score.
        score = max(_similarity(target, r.normalized_name),
                    _similarity(target_canon, canonical_company(r.normalized_name)))
        if score >= threshold:
            out.append({
                "id": str(r.id),
                "entity_name": r.entity_name,
                "category": r.category.value,
                "source": r.source,
                "url": r.url,
                "summary": r.summary,
                "score": score,
            })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def has_adverse_media(db: Session, name: str, threshold: int = MATCH_THRESHOLD) -> bool:
    return len(screen_name(db, name, threshold)) > 0


def add_record(db: Session, data: dict) -> AdverseMediaRecord:
    data = dict(data)
    data["normalized_name"] = normalize_name(data.get("entity_name", ""))
    obj = AdverseMediaRecord(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_records(db: Session, limit: int = 200) -> list[AdverseMediaRecord]:
    return list(db.execute(
        select(AdverseMediaRecord).order_by(AdverseMediaRecord.created_at.desc()).limit(limit)
    ).scalars().all())


_SEED = [
    ("Viktor Petrov", AdverseMediaCategory.MONEY_LAUNDERING,
     "ICIJ", "Enquête sur un réseau de blanchiment transfrontalier."),
    ("Global Mining SARL", AdverseMediaCategory.CORRUPTION,
     "OCCRP", "Soupçons de corruption liés à l'attribution de licences minières."),
    ("Ahmed Al-Rashid", AdverseMediaCategory.TERRORISM,
     "Reuters", "Cité dans une enquête sur le financement du terrorisme."),
    ("Sofia Ndiaye", AdverseMediaCategory.FRAUD,
     "Le Monde", "Mise en cause dans une affaire de fraude financière."),
]


def seed_adverse_media(db: Session) -> int:
    existing = {r.entity_name for r in list_records(db)}
    n = 0
    for name, cat, source, summary in _SEED:
        if name not in existing:
            db.add(AdverseMediaRecord(
                entity_name=name, normalized_name=normalize_name(name),
                category=cat, source=source, summary=summary,
            ))
            n += 1
    db.commit()
    return n


# ─── Pistes presse (GDELT) ────────────────────────────────────────────────────
#
# Source libre et mondiale, en appoint de la base interne. Elle ne fait PAS
# foi : la précision est faible (un article peut évoquer un thème sans lien
# réel avec l'entité), et les résultats sont donc présentés comme des pistes
# à trier, jamais comme un motif de décision.

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_ATTRIBUTION = "Source : The GDELT Project — presse mondiale, résultats non vérifiés."

# Thèmes GDELT retenus comme défavorables. Sans ce filtre, une recherche sur
# une société renvoie surtout de l'actualité neutre (résultats financiers,
# partenariats), ce qui noierait le signal.
_GDELT_THEMES = (
    "theme:CORRUPTION OR theme:FINCRIME OR theme:ECON_MONEY_LAUNDERING "
    "OR theme:TAX_FNCACT_FRAUD OR theme:TERRORISM OR theme:TRAFFICKING "
    "OR theme:SCANDAL OR theme:ARREST"
)

# GDELT impose une requête toutes les 5 s et répond 429 au-delà. Un verrou de
# processus espace les appels ; le cache évite de la solliciter deux fois pour
# la même société.
_GDELT_MIN_INTERVAL_S = 5.5
_gdelt_lock = threading.Lock()
_gdelt_last_call = [0.0]

_PRESS_TTL_S = 6 * 3600
_press_cache: dict[str, tuple[float, list[dict]]] = {}


def _gdelt_query(name: str, months: int) -> list[dict]:
    query = f'"{name}" ({_GDELT_THEMES})'
    url = (f"{GDELT_URL}?query={urllib.parse.quote(query)}"
           f"&mode=artlist&maxrecords=20&format=json&sort=datedesc"
           f"&timespan={max(1, months)}m")
    req = urllib.request.Request(url, headers={"User-Agent": "Simandou-LBCFT/1.0"})
    with _gdelt_lock:
        wait = _GDELT_MIN_INTERVAL_S - (time.monotonic() - _gdelt_last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            raw = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        finally:
            _gdelt_last_call[0] = time.monotonic()
    # Hors quota, GDELT répond en texte brut et non en JSON.
    if not raw.lstrip().startswith("{"):
        raise RuntimeError(raw.strip()[:120] or "réponse GDELT vide")
    return json.loads(raw).get("articles") or []


def search_press(name: str, months: int = 24) -> dict:
    """
    Pistes de presse pour une dénomination sociale.

    Ne lève jamais : la presse est un appoint, son indisponibilité ne doit pas
    faire échouer une vérification.
    """
    key = f"{normalize_name(name)}|{months}"
    hit = _press_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _PRESS_TTL_S:
        return {"name": name, "articles": hit[1], "attribution": GDELT_ATTRIBUTION,
                "cached": True, "error": None}
    try:
        arts = _gdelt_query(name, months)
    except Exception as e:
        logger.warning("gdelt_unavailable", extra={"reason": str(e)[:200]})
        return {"name": name, "articles": [], "attribution": GDELT_ATTRIBUTION,
                "cached": False, "error": "Source de presse momentanément indisponible."}

    out = [{
        "title": (a.get("title") or "").strip(),
        "url": a.get("url"),
        "domain": a.get("domain"),
        "language": a.get("language"),
        "seen_at": (a.get("seendate") or "")[:8],
    } for a in arts if (a.get("title") or "").strip()]
    _press_cache[key] = (time.monotonic(), out)
    return {"name": name, "articles": out, "attribution": GDELT_ATTRIBUTION,
            "cached": False, "error": None}


def assess_company(db: Session, name: str) -> dict:
    """
    Volet « médias défavorables » d'une vérification de personne morale.

    N'interroge que la base interne : elle seule fait foi et peut peser sur le
    risque. La presse est consultée à la demande depuis l'écran, pour ne pas
    soumettre chaque vérification à la disponibilité d'un service externe.
    """
    matches = screen_name(db, name)
    if not matches:
        return {"hit": False, "matches": [], "risk_floor": None, "severity": None}

    # Le plancher de risque tient compte de la FORCE du rapprochement autant
    # que de la gravité du fait. « Atlas Trading SA » ressemble à 67 % à
    # « Atlas Trading Ltd » sans être la même société : un rapprochement
    # seulement possible ne doit pas porter le dossier en risque élevé.
    # Il déclenche un examen humain, ce qui est le bon niveau de réaction.
    strong = [m for m in matches if m["score"] >= STRONG_MATCH_SCORE]
    severe = any(m["category"] in _SEVERE for m in strong)
    return {
        "hit": True,
        "matches": matches,
        "risk_floor": "HIGH" if severe else "MEDIUM",
        "severity": "SEVERE" if severe else "STANDARD",
        "strong": bool(strong),
    }
