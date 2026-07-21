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

# GDELT annonce « une requête toutes les 5 s », mais la mesure contredit cette
# lecture : espacés de 30 s depuis une seule adresse IP, 11 appels n'ont abouti
# que 4 fois (36 %), et les succès ne suivent aucun rythme régulier. Le quota
# est donc global, pas fonction de l'intervalle — espacer davantage ne sert à
# rien, seule la RELANCE rattrape les refus.
#
# Conséquence assumée : la recherche de presse n'est pas fiable à 100 %. Elle
# reste un appoint informatif, jamais un élément de décision — et le cache fait
# qu'une société interrogée une fois répond ensuite instantanément.
_GDELT_MIN_INTERVAL_S = 2.0
_GDELT_ATTEMPTS = 3
_GDELT_RETRY_WAIT_S = 7.0
_gdelt_lock = threading.Lock()
_gdelt_last_call = [0.0]

_PRESS_TTL_H = 6
# Au-delà, une recherche restée « en cours » est tenue pour perdue (worker
# redémarré en plein vol) et peut être relancée.
_PRESS_STALE_MIN = 5


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


def press_status(db: Session, name: str) -> dict:
    """
    État de la recherche de presse pour une dénomination.

    Ne déclenche rien : c'est ce que sonde l'écran. Renvoie toujours un statut
    exploitable — IDLE (jamais cherché), PENDING, DONE ou ERROR.
    """
    key = normalize_name(name or "")[:300]
    row = db.execute(text("""
        SELECT status, articles, error,
               EXTRACT(EPOCH FROM (now() - updated_at)) / 3600 AS age_h,
               EXTRACT(EPOCH FROM (now() - started_at)) / 60   AS run_min
          FROM press_search_cache WHERE name_normalized = :k
    """), {"k": key}).mappings().first()

    if not row:
        return {"status": "IDLE", "articles": [], "error": None,
                "attribution": GDELT_ATTRIBUTION}

    # Recherche en cours depuis trop longtemps : le worker qui la portait a
    # sans doute disparu. On la déclare perdue plutôt que de faire tourner
    # l'écran indéfiniment.
    if row["status"] == "PENDING" and float(row["run_min"] or 0) > _PRESS_STALE_MIN:
        return {"status": "IDLE", "articles": [], "error": None,
                "attribution": GDELT_ATTRIBUTION}

    if row["status"] == "DONE" and float(row["age_h"] or 0) > _PRESS_TTL_H:
        return {"status": "IDLE", "articles": [], "error": None,
                "attribution": GDELT_ATTRIBUTION}

    return {"status": row["status"], "articles": row["articles"] or [],
            "error": row["error"], "attribution": GDELT_ATTRIBUTION}


def press_start(db: Session, name: str) -> dict:
    """
    Déclenche une recherche en arrière-plan si nécessaire, et rend la main
    aussitôt. La source refuse environ deux requêtes sur trois et chaque
    tentative peut durer une minute : faire patienter l'appel HTTP jusqu'au
    bout donnerait un écran figé pour, souvent, un échec.
    """
    current = press_status(db, name)
    if current["status"] in ("DONE", "PENDING", "ERROR"):
        return current

    key = normalize_name(name or "")[:300]
    db.execute(text("""
        INSERT INTO press_search_cache
            (name_normalized, display_name, status, articles, error, started_at, updated_at)
        VALUES (:k, :n, 'PENDING', NULL, NULL, now(), now())
        ON CONFLICT (name_normalized) DO UPDATE
           SET status = 'PENDING', articles = NULL, error = NULL,
               started_at = now(), updated_at = now()
    """), {"k": key, "n": (name or "")[:300]})
    db.commit()

    threading.Thread(target=_press_worker, args=(key, name), daemon=True).start()
    return {"status": "PENDING", "articles": [], "error": None,
            "attribution": GDELT_ATTRIBUTION}


def _press_worker(key: str, name: str) -> None:
    """
    Interroge la source hors du cycle de la requête HTTP.

    Ouvre sa PROPRE session : celle de la requête est refermée bien avant que
    ce fil ne se termine.
    """
    from app.core.db import SessionLocal

    articles: list[dict] = []
    err = None
    try:
        arts = None
        last = ""
        for attempt in range(_GDELT_ATTEMPTS):
            try:
                arts = _gdelt_query(name, 24)
                break
            except Exception as e:
                last = str(e)[:200]
                if attempt < _GDELT_ATTEMPTS - 1:
                    time.sleep(_GDELT_RETRY_WAIT_S)
        if arts is None:
            err = "La source de presse limite ses requêtes ; réessayez dans un instant."
            logger.warning("gdelt_unavailable", extra={"reason": last})
        else:
            articles = [{
                "title": (a.get("title") or "").strip(),
                "url": a.get("url"),
                "domain": a.get("domain"),
                "language": a.get("language"),
                "seen_at": (a.get("seendate") or "")[:8],
            } for a in arts if (a.get("title") or "").strip()]
    except Exception as e:  # défaillance inattendue : l'écran ne doit pas tourner sans fin
        err = "Recherche de presse interrompue."
        logger.exception("press_worker_failed", extra={"reason": str(e)[:200]})

    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE press_search_cache
               SET status = :st, articles = CAST(:a AS jsonb), error = :e, updated_at = now()
             WHERE name_normalized = :k
        """), {"st": "ERROR" if err else "DONE",
               "a": json.dumps(articles, ensure_ascii=False),
               "e": err, "k": key})
        db.commit()
    except Exception:
        logger.exception("press_cache_write_failed")
    finally:
        db.close()


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
