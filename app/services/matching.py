# app/services/matching.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.cache import cache, make_key
from app.core.config import settings
from app.core.logging import get_logger
from app.models.screening_db import ScreeningMatch

logger = get_logger("simandou.matching")


# -----------------------------------------------------------------------------
# Data structures
# -----------------------------------------------------------------------------

@dataclass
class Candidate:
    entity_id: str
    entity_risk: str
    primary_name: str
    best_name_id: int
    best_norm: str
    trigram_sim: float
    token_overlap: float
    score: int

    # ✅ NEW: best source record for sanction/source explainability
    source_record_id: Optional[str] = None
    source_id: Optional[int] = None


# -----------------------------------------------------------------------------
# Normalization + scoring
# -----------------------------------------------------------------------------

def normalize_name(s: str) -> str:
    s = (s or "").strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(norm: str) -> list[str]:
    norm = (norm or "").strip()
    return [t for t in norm.split(" ") if len(t) >= 2]

def score_candidate(trigram_sim: float, token_overlap: float) -> int:
    # simple, explainable: 70% trigram + 30% token overlap
    v = (0.7 * trigram_sim + 0.3 * token_overlap) * 100.0
    v = max(0, min(100, int(round(v))))
    return v

def band(score: int) -> str:
    if score >= 85:
        return "STRONG"
    if score >= 65:
        return "POSSIBLE"
    return "WEAK"


# -----------------------------------------------------------------------------
# ✅ NEW: pick best SourceRecord for an entity
# -----------------------------------------------------------------------------

def pick_best_source_record_id(db: Session, entity_id: str) -> tuple[Optional[str], Optional[int]]:
    """
    Returns (source_record_id, source_id) for the "best" source record of an entity.

    Heuristic (stable and explainable):
      1) prefer records with listed_on (latest listed_on)
      2) then prefer records with non-empty summary
      3) then prefer latest created_at
    """
    # We use SQL to avoid model attribute mismatches across migrations.
    sql = text(
        """
        SELECT
          sr.id::text AS id,
          sr.source_id::int AS source_id,
          sr.listed_on,
          sr.created_at,
          sr.summary
        FROM source_records sr
        WHERE sr.entity_id = :eid
        ORDER BY
          (sr.listed_on IS NOT NULL) DESC,
          sr.listed_on DESC NULLS LAST,
          (sr.summary IS NOT NULL AND sr.summary <> '') DESC,
          sr.created_at DESC NULLS LAST,
          sr.id DESC
        LIMIT 1
        """
    )
    row = db.execute(sql, {"eid": entity_id}).mappings().first()
    if not row:
        return None, None
    return (row["id"], int(row["source_id"]) if row.get("source_id") is not None else None)


# -----------------------------------------------------------------------------
# Candidate retrieval (pg_trgm)
# -----------------------------------------------------------------------------

def _candidate_to_dict(c: Candidate) -> dict[str, Any]:
    return {
        "entity_id": c.entity_id,
        "entity_risk": c.entity_risk,
        "primary_name": c.primary_name,
        "best_name_id": c.best_name_id,
        "best_norm": c.best_norm,
        "trigram_sim": c.trigram_sim,
        "token_overlap": c.token_overlap,
        "score": c.score,
        "source_record_id": c.source_record_id,
        "source_id": c.source_id,
    }


def _candidate_from_dict(d: dict[str, Any]) -> Candidate:
    return Candidate(
        entity_id=d["entity_id"],
        entity_risk=d["entity_risk"],
        primary_name=d["primary_name"],
        best_name_id=int(d["best_name_id"]),
        best_norm=d["best_norm"],
        trigram_sim=float(d["trigram_sim"]),
        token_overlap=float(d["token_overlap"]),
        score=int(d["score"]),
        source_record_id=d.get("source_record_id"),
        source_id=d.get("source_id"),
    )


def retrieve_candidates(
    db: Session,
    input_norm: str,
    input_tokens: list[str],
    limit: int = 25,
    attach_best_source_record: bool = True,
) -> list[Candidate]:
    """
    Uses pg_trgm (idx_entity_names_trgm) on entity_names.name_normalized,
    then aggregates best match per entity_id.

    ✅ Optionally attaches best source_record_id per entity for later match explainability.

    Caching (S2):
      Si Redis est branché, on cache (input_norm, tokens, limit, attach_best_source_record)
      → liste de Candidate. TTL = MATCHING_CACHE_TTL_SECONDS (5min par défaut).
      Invalidation manuelle via invalidate_matching_cache() après import OFAC/EU/UN.
    """
    cache_key = None
    if settings.cache_enabled:
        cache_key = make_key(
            "matching:cand",
            input_norm,
            ",".join(sorted(input_tokens or [])),
            limit,
            int(attach_best_source_record),
        )
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("matching_cache_hit", extra={"key": cache_key, "n": len(cached)})
            return [_candidate_from_dict(d) for d in cached]

    sql = text(
        """
        SELECT
          e.id::text as entity_id,
          e.risk_level::text as entity_risk,
          e.primary_name as primary_name,
          en.id as name_id,
          en.name_normalized as name_normalized,
          similarity(en.name_normalized, :q) as sim
        FROM entity_names en
        JOIN entities e ON e.id = en.entity_id
        WHERE en.name_normalized % :q
          -- Une personne retirée d'une liste ne doit plus être signalée. Sans
          -- cette exclusion, une levée de sanction n'aurait aucun effet et
          -- l'entité resterait rapprochée indéfiniment.
          -- L'entité est écartée seulement si TOUTES ses inscriptions sont
          -- radiées : une même personne peut figurer sur plusieurs listes et
          -- n'être retirée que de l'une d'elles.
          AND NOT EXISTS (
              SELECT 1 FROM source_records sr
               WHERE sr.entity_id = e.id
              HAVING bool_and(sr.unlisted_on IS NOT NULL)
          )
        ORDER BY sim DESC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"q": input_norm, "lim": limit}).mappings().all()

    in_set = set(input_tokens) if input_tokens else set()

    best_by_entity: dict[str, Candidate] = {}
    for r in rows:
        cand_tokens = set((r["name_normalized"] or "").split(" "))
        overlap = (len(in_set & cand_tokens) / max(1, len(in_set))) if in_set else 0.0
        sc = score_candidate(float(r["sim"] or 0.0), overlap)

        c = Candidate(
            entity_id=r["entity_id"],
            entity_risk=r["entity_risk"],
            primary_name=r["primary_name"],
            best_name_id=int(r["name_id"]),
            best_norm=r["name_normalized"],
            trigram_sim=float(r["sim"] or 0.0),
            token_overlap=float(overlap),
            score=sc,
        )

        prev = best_by_entity.get(c.entity_id)
        if (prev is None) or (c.score > prev.score):
            best_by_entity[c.entity_id] = c

    # ✅ Attach best source record AFTER we have the final candidates (avoid N*M work)
    out = sorted(best_by_entity.values(), key=lambda x: x.score, reverse=True)

    if attach_best_source_record and out:
        for c in out:
            sr_id, src_id = pick_best_source_record_id(db, c.entity_id)
            c.source_record_id = sr_id
            c.source_id = src_id

    if cache_key is not None:
        cache.set(
            cache_key,
            [_candidate_to_dict(c) for c in out],
            ttl=settings.MATCHING_CACHE_TTL_SECONDS,
        )

    return out


def invalidate_matching_cache() -> int:
    """À appeler après un import OFAC/EU/UN/PEP pour invalider les résultats cachés."""
    n = cache.delete_pattern("matching:cand:*")
    logger.info("matching_cache_invalidated", extra={"keys_deleted": n})
    return n


# -----------------------------------------------------------------------------
# Reasons/explanations
# -----------------------------------------------------------------------------

def build_match_reasons(
    input_norm: str,
    candidate: Candidate,
) -> dict[str, Any]:
    """
    ✅ NEW: a consistent reasons payload used by both admin & analyst.
    This is the object your frontend already renders nicely.
    """
    return {
        "input_normalized": input_norm,
        "matched_normalized": candidate.best_norm,
        "primary_name": candidate.primary_name,
        "best_name_id": candidate.best_name_id,
        "trigram_similarity": float(candidate.trigram_sim),
        "token_overlap": float(candidate.token_overlap),
        "score": int(candidate.score),
        "band": band(candidate.score),
        # ✅ crucial: link to sanction/source
        "source_record_id": candidate.source_record_id,
        "source_id": candidate.source_id,
    }


def explain_match(m: ScreeningMatch) -> dict[str, Any]:
    """
    Kept for admin debugging (ScreeningMatchOut.explanation),
    but aligned to the reasons keys you now generate.
    """
    reasons = m.reasons or {}
    explanations: list[str] = []

    try:
        if float(reasons.get("trigram_similarity") or 0.0) >= 0.999:
            explanations.append("Nom strictement identique après normalisation")
    except Exception:
        pass

    tok = reasons.get("token_overlap")
    if tok is not None:
        try:
            explanations.append(f"Mots en commun (token overlap) : {int(tok)}")
        except Exception:
            explanations.append(f"Mots en commun (token overlap) : {tok}")

    inp = reasons.get("input_normalized")
    mat = reasons.get("matched_normalized")
    if inp and mat:
        explanations.append(f"Nom analysé : « {inp} » → trouvé : « {mat} »")

    return {
        "technical": reasons,
        "summary": " ; ".join(explanations) if explanations else "Correspondance détectée par le moteur",
        "score": getattr(m, "match_score", None),
        "band": getattr(m, "match_band", None),
        "source_record_id": getattr(m, "source_record_id", None),
    }
