from __future__ import annotations
import math
from typing import Optional
from uuid import UUID
from app.api.deps.auth import get_current_user
from datetime import date, timedelta
from typing import Any
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, select, func
from uuid import UUID
from datetime import date, timedelta

from app.api.deps.db import get_db_rls as get_db
from app.models.screening_db import (
    Entity, EntityName, SourceRecord,
    ScreeningRequest, ScreeningResult, ScreeningMatch
)
from app.services.matching import normalize_name
from app.services.matching import explain_match
from app.schemas.admin import (
    EntityOut, EntityNameOut, SourceRecordOut,
    EntitySearchHit, Paged,
    ScreeningRequestListItem, ScreeningRequestDetail,
    ScreeningMatchOut, ScreeningResultOut
)


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)
def get_default_user_id(db: Session):
    q = text("select id from users order by created_at asc limit 1")
    uid = db.execute(q).scalar()
    if not uid:
        raise HTTPException(status_code=400, detail="No users found. Create an admin user first.")
    return uid

# Fallback si la table sources n'a pas code/name (ou si elle n'existe pas)
SOURCE_FALLBACK = {
    1: "UN",
    2: "OFAC",
    3: "EU",
}

def _score_hint(sim: float) -> int:
    # juste un indicateur: 0..100
    v = int(round(max(0.0, min(1.0, sim)) * 100))
    return v
def _sources_columns(db: Session) -> set[str]:
    """
    Retourne les colonnes existantes dans public.sources.
    Si la table n'existe pas, retourne set().
    """
    try:
        rows = db.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='sources'
                """
            )
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        db.rollback()
        return set()
def _exec(db: Session, sql: str, params: dict | None = None):
    try:
        return db.execute(text(sql), params or {})
    except Exception:
        db.rollback()
        raise


@router.get("/_debug/db")
def debug_db(db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT
          current_database() AS db,
          current_schema() AS schema,
          inet_server_addr()::text AS server_addr,
          inet_server_port() AS server_port,
          version() AS version
    """)).mappings().first()

    # bonus: chemin / settings env si tu veux voir l'URL, mais sans exposer le password
    return dict(row or {})


@router.get("/entities/search", response_model=Paged)
def search_entities(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = Query(None, description="person|company"),
    risk_level: Optional[str] = Query(None, description="LOW|MEDIUM|HIGH"),
    db: Session = Depends(get_db),
):
    """
    Recherche admin basée sur pg_trgm sur entity_names.name_normalized.
    Renvoie 1 hit par entity (best match).
    """
    qnorm = normalize_name(q)

    # WHERE dynamiques (sans ORM pour garder DISTINCT ON + similarity)
    filters = []
    params = {"q": qnorm, "limit": limit, "offset": offset}

    if entity_type:
        filters.append("e.entity_type = :entity_type")
        params["entity_type"] = entity_type

    if risk_level:
        filters.append("e.risk_level = :risk_level")
        params["risk_level"] = risk_level

    where_extra = ""
    if filters:
        where_extra = " AND " + " AND ".join(filters)

    # Total count: on compte les entities distinctes matchant q
    total_sql = text(f"""
        SELECT count(*)::int AS total
        FROM (
            SELECT DISTINCT e.id
            FROM entity_names en
            JOIN entities e ON e.id = en.entity_id
            WHERE en.name_normalized % :q
            {where_extra}
        ) t
    """)
    total = db.execute(total_sql, params).scalar_one()

    # Hits paginés: DISTINCT ON(entity_id) + best similarity
    hits_sql = text(f"""
    WITH ranked AS (
        SELECT
            e.id::uuid AS entity_id,
            e.entity_type::text AS entity_type,
            e.primary_name AS primary_name,
            e.risk_level::text AS risk_level,
            en.name_normalized AS best_norm,
            similarity(en.name_normalized, :q) AS sim
        FROM entity_names en
        JOIN entities e ON e.id = en.entity_id
        WHERE en.name_normalized % :q
        {where_extra}
    ),
    best AS (
        SELECT DISTINCT ON (entity_id)
            entity_id, entity_type, primary_name, risk_level, best_norm, sim
        FROM ranked
        ORDER BY entity_id, sim DESC
    ),
    sr_counts AS (
        SELECT entity_id, COUNT(*)::int AS source_count
        FROM source_records
        GROUP BY entity_id
    ),
    name_counts AS (
        SELECT entity_id, COUNT(*)::int AS names_count
        FROM entity_names
        GROUP BY entity_id
    )
    SELECT
        b.entity_id::text AS entity_id,
        b.entity_type,
        b.primary_name,
        b.risk_level,
        b.best_norm,
        b.sim,
        COALESCE(sr_counts.source_count, 0) AS source_count,
        COALESCE(name_counts.names_count, 0) AS names_count
    FROM best b
    LEFT JOIN sr_counts ON sr_counts.entity_id = b.entity_id
    LEFT JOIN name_counts ON name_counts.entity_id = b.entity_id
    ORDER BY b.sim DESC
    LIMIT :limit OFFSET :offset
""")

    rows = db.execute(hits_sql, params).mappings().all()
    items = [
        EntitySearchHit(
            entity_id=r["entity_id"],
            entity_type=r["entity_type"],
            primary_name=r["primary_name"],
            risk_level=r["risk_level"],
            best_norm=r["best_norm"],
            similarity=float(r["sim"] or 0.0),
            score_hint=_score_hint(float(r["sim"] or 0.0)),
            source_count=int(r["source_count"] or 0),
            names_count=int(r["names_count"] or 0),
        )
        for r in rows
    ]

    return {"items": items, "limit": limit, "offset": offset, "total": total}

@router.get("/entities/by-id/{entity_id}", response_model=EntityOut)
def get_entity(entity_id: str, db: Session = Depends(get_db)):
    try:
        eid = UUID(entity_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid entity_id")

    ent = db.get(Entity, eid)
    if not ent:
        raise HTTPException(status_code=404, detail="entity not found")

    names = db.execute(
        select(EntityName)
        .where(EntityName.entity_id == eid)
        .order_by(EntityName.is_primary.desc(), EntityName.id.asc())
    ).scalars().all()

    sources = db.execute(
        select(SourceRecord)
        .where(SourceRecord.entity_id == eid)
        .order_by(SourceRecord.created_at.desc())
    ).scalars().all()

    return EntityOut(
        id=str(ent.id),
        entity_type=ent.entity_type,
        primary_name=ent.primary_name,
        country_focus=ent.country_focus,
        risk_level=ent.risk_level,
        created_at=str(ent.created_at),
        updated_at=str(ent.updated_at),
        names=[
            EntityNameOut(
                id=n.id,
                name_raw=n.name_raw,
                name_normalized=n.name_normalized,
                is_primary=bool(n.is_primary),
                name_type=n.name_type,
            )
            for n in names
        ],
        sources=[
            SourceRecordOut(
                id=str(s.id),
                source_id=int(s.source_id),
                source_ref=s.source_ref,
                record_type=s.record_type,
                program=s.program,
                listed_on=str(s.listed_on) if s.listed_on else None,
                unlisted_on=str(s.unlisted_on) if s.unlisted_on else None,
                summary=s.summary,
                evidence_urls=s.evidence_urls,
                raw_payload=s.raw_payload,
            )
            for s in sources
        ],
    )


@router.get("/screening/requests", response_model=Paged)
def list_screening_requests(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = select(ScreeningRequest).order_by(ScreeningRequest.created_at.desc())
    if client_id:
        q = q.where(ScreeningRequest.client_id == client_id)

    total = db.execute(
        select(func.count()).select_from(q.subquery())
    ).scalar_one()

    rows = db.execute(q.limit(limit).offset(offset)).scalars().all()

    items = [
        ScreeningRequestListItem(
            id=str(r.id),
            client_id=r.client_id,
            created_at=str(r.created_at),
            request_payload=r.request_payload,
        )
        for r in rows
    ]
    return {"items": items, "limit": limit, "offset": offset, "total": int(total)}


@router.get("/screening/requests/{request_id}", response_model=ScreeningRequestDetail)
def get_screening_request(request_id: str, db: Session = Depends(get_db)):
    try:
        rid = UUID(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid request_id")

    req = db.get(ScreeningRequest, rid)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")

    res = db.execute(
        select(ScreeningResult).where(ScreeningResult.request_id == rid)
    ).scalar_one_or_none()

    matches = db.execute(
        select(ScreeningMatch)
        .where(ScreeningMatch.request_id == rid)
        .order_by(ScreeningMatch.match_score.desc(), ScreeningMatch.id.asc())
    ).scalars().all()

    return ScreeningRequestDetail(
        request=ScreeningRequestListItem(
            id=str(req.id),
            client_id=req.client_id,
            created_at=str(req.created_at),
            request_payload=req.request_payload,
        ),
        result=(
            ScreeningResultOut(
                id=str(res.id),
                request_id=str(res.request_id),
                risk_level=res.risk_level,
                confidence=int(res.confidence),
                recommended_action=res.recommended_action,
                decided_by=res.decided_by,
                decided_at=str(res.decided_at),
                notes=res.notes,
            )
            if res else None
        ),
        matches=[
            ScreeningMatchOut(
                id=m.id,
                request_id=str(m.request_id),
                entity_id=str(m.entity_id),
                source_record_id=str(m.source_record_id) if m.source_record_id else None,
                match_score=int(m.match_score),
                match_band=m.match_band,
                reasons=m.reasons,
                created_at=str(m.created_at),
                explanation=explain_match(m),
            )
            for m in matches
        ],
    )

@router.get("/entities/duplicates")
def entities_duplicates(
    threshold: float = Query(0.9, ge=0.0, le=1.0),
    limit_pairs: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    top_k: int = Query(5, ge=1, le=50),
    scan_limit: int = Query(2000, ge=100, le=200000),
    min_len: int = Query(8, ge=1, le=50),
    timeout_ms: int = Query(30000, ge=1000, le=120000),
    db: Session = Depends(get_db),
):
    t = float(max(0.0, min(1.0, threshold)))
    tm = int(max(1000, min(120000, timeout_ms)))

    sql = text("""
      WITH base AS (
        SELECT
          en.id AS en_id,
          en.entity_id AS entity_id,
          e.primary_name AS primary_name,
          en.name_normalized AS norm
        FROM entity_names en
        JOIN entities e ON e.id = en.entity_id
        WHERE en.is_primary = true
          AND en.name_normalized IS NOT NULL
          AND en.name_normalized <> ''
          AND char_length(en.name_normalized) >= :min_len
        ORDER BY en.id
        LIMIT :scan_limit
      )
      SELECT
        b.entity_id::text AS entity_id_1,
        e2.id::text       AS entity_id_2,
        b.primary_name    AS primary_name_1,
        e2.primary_name   AS primary_name_2,
        b.norm            AS norm_1,
        cand.norm_2       AS norm_2,
        cand.sim          AS sim
      FROM base b
      JOIN LATERAL (
        SELECT
          en2.entity_id AS entity_id_2,
          en2.name_normalized AS norm_2,
          similarity(en2.name_normalized, b.norm) AS sim
        FROM entity_names en2
        WHERE en2.is_primary = true
          AND en2.id > b.en_id
          AND char_length(en2.name_normalized) >= :min_len
          AND en2.name_normalized % b.norm
        ORDER BY sim DESC
        LIMIT :top_k
      ) cand ON TRUE
      JOIN entities e2 ON e2.id = cand.entity_id_2
      WHERE cand.sim >= :threshold
      ORDER BY cand.sim DESC
      LIMIT :limit OFFSET :offset;
    """)

    params = {
        "threshold": t,
        "limit": limit_pairs,
        "offset": offset,
        "top_k": top_k,
        "scan_limit": scan_limit,
        "min_len": min_len,
    }

    try:
        # transaction + SET LOCAL
        db.execute(text("BEGIN"))
        db.execute(text(f"SET LOCAL statement_timeout = '{tm}ms'"))
        db.execute(text(f"SET LOCAL pg_trgm.similarity_threshold = '{t}'"))

        rows = db.execute(sql, params).mappings().all()
        db.execute(text("COMMIT"))

        items = [
            {
                "entity_id_1": r["entity_id_1"],
                "entity_id_2": r["entity_id_2"],
                "primary_name_1": r["primary_name_1"],
                "primary_name_2": r["primary_name_2"],
                "norm_1": r["norm_1"],
                "norm_2": r["norm_2"],
                "similarity": float(r["sim"] or 0.0),
                "score_hint": _score_hint(float(r["sim"] or 0.0)),
            }
            for r in rows
        ]

        return {
            "threshold": t,
            "limit": limit_pairs,
            "offset": offset,
            "top_k": top_k,
            "scan_limit": scan_limit,
            "min_len": min_len,
            "timeout_ms": tm,
            "count": len(items),
            "items": items,
        }

    except Exception:
        db.rollback()
        raise

@router.post("/reindex")
def admin_reindex(
    dry_run: bool = Query(False),
    limit: int = Query(20000, ge=1, le=5_000_000),
    batch_size: int = Query(1000, ge=50, le=10000),
    only_primary: bool = Query(False, description="Only reindex primary names"),
    db: Session = Depends(get_db),
):
    """
    Recalcule entity_names.name_normalized = normalize_name(name_raw).
    Safe maintenance:
    - batch
    - dry_run
    - advisory lock pour éviter 2 reindex en parallèle
    """

    lock_key = 918273
    got_lock = db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar_one()
    if not got_lock:
        raise HTTPException(status_code=409, detail="reindex already running")

    updated = 0
    scanned = 0

    try:
        last_id = 0
        while scanned < limit:
            extra = "AND en.is_primary = true" if only_primary else ""
            batch_sql = text(f"""
                SELECT en.id, en.name_raw, en.name_normalized
                FROM entity_names en
                WHERE en.id > :last_id
                {extra}
                ORDER BY en.id ASC
                LIMIT :batch_size
            """)

            batch = db.execute(batch_sql, {"last_id": last_id, "batch_size": batch_size}).mappings().all()
            if not batch:
                break

            scanned += len(batch)
            last_id = int(batch[-1]["id"])

            to_update = []
            for r in batch:
                raw = r["name_raw"] or ""
                new_norm = normalize_name(raw)
                old_norm = r["name_normalized"] or ""
                if new_norm != old_norm:
                    to_update.append({"id": int(r["id"]), "name_normalized": new_norm})

            if to_update:
                updated += len(to_update)
                if not dry_run:
                    db.execute(
                        text("UPDATE entity_names SET name_normalized = :name_normalized WHERE id = :id"),
                        to_update,
                    )
                    db.commit()
                else:
                    db.rollback()

        return {
            "dry_run": dry_run,
            "only_primary": only_primary,
            "limit": limit,
            "batch_size": batch_size,
            "scanned": scanned,
            "updated": updated,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
        db.commit()

@router.get("/stats")
def admin_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Stats admin:
    - entities par source (distinct entity_id via source_records)
    - entities par risk_level (table entities)
    - screenings par jour (table screening_requests)
    """

    cols = _sources_columns(db)
    has_sources = bool(cols)
    has_code = "code" in cols
    has_name = "name" in cols

    # 1) Entities par source
    entities_by_source: list[dict[str, Any]] = []

    try:
        if has_sources and (has_code or has_name):
            # Construire SELECT dynamique selon colonnes présentes
            select_code = "COALESCE(s.code::text, '') AS source_code," if has_code else "''::text AS source_code,"
            select_name = "COALESCE(s.name::text, '') AS source_name," if has_name else "''::text AS source_name,"

            group_code = ", s.code" if has_code else ""
            group_name = ", s.name" if has_name else ""

            rows = db.execute(
                text(
                    f"""
                    SELECT
                      sr.source_id::int              AS source_id,
                      {select_code}
                      {select_name}
                      COUNT(DISTINCT sr.entity_id)   AS entities,
                      COUNT(*)                       AS source_records
                    FROM source_records sr
                    LEFT JOIN sources s ON s.id = sr.source_id
                    GROUP BY sr.source_id{group_code}{group_name}
                    ORDER BY entities DESC;
                    """
                )
            ).mappings().all()

            for r in rows:
                sid = int(r["source_id"])
                code = (r.get("source_code") or "").strip() or SOURCE_FALLBACK.get(sid, f"SOURCE_{sid}")
                name = (r.get("source_name") or "").strip() or None
                entities_by_source.append(
                    {
                        "source_id": sid,
                        "source_code": code,
                        "source_name": name,
                        "entities": int(r["entities"]),
                        "source_records": int(r["source_records"]),
                    }
                )
        else:
            # Pas de table sources, ou pas de colonnes exploitables
            rows = db.execute(
                text(
                    """
                    SELECT
                      sr.source_id::int            AS source_id,
                      COUNT(DISTINCT sr.entity_id) AS entities,
                      COUNT(*)                     AS source_records
                    FROM source_records sr
                    GROUP BY sr.source_id
                    ORDER BY entities DESC;
                    """
                )
            ).mappings().all()

            for r in rows:
                sid = int(r["source_id"])
                entities_by_source.append(
                    {
                        "source_id": sid,
                        "source_code": SOURCE_FALLBACK.get(sid, f"SOURCE_{sid}"),
                        "source_name": None,
                        "entities": int(r["entities"]),
                        "source_records": int(r["source_records"]),
                    }
                )

    except Exception:
        # IMPORTANT: reset transaction après erreur
        db.rollback()

        # Fallback minimal sûr
        rows = db.execute(
            text(
                """
                SELECT
                  sr.source_id::int            AS source_id,
                  COUNT(DISTINCT sr.entity_id) AS entities,
                  COUNT(*)                     AS source_records
                FROM source_records sr
                GROUP BY sr.source_id
                ORDER BY entities DESC;
                """
            )
        ).mappings().all()

        for r in rows:
            sid = int(r["source_id"])
            entities_by_source.append(
                {
                    "source_id": sid,
                    "source_code": SOURCE_FALLBACK.get(sid, f"SOURCE_{sid}"),
                    "source_name": None,
                    "entities": int(r["entities"]),
                    "source_records": int(r["source_records"]),
                }
            )

    # 2) Entities par risk_level
    entities_by_risk = db.execute(
        text(
            """
            SELECT
              e.risk_level::text AS risk_level,
              COUNT(*)::int      AS entities
            FROM entities e
            GROUP BY e.risk_level
            ORDER BY COUNT(*) DESC;
            """
        )
    ).mappings().all()

    entities_by_risk_out = [
        {"risk_level": r["risk_level"], "entities": int(r["entities"])}
        for r in entities_by_risk
    ]

    # 3) Screenings par jour (N derniers jours)
    start_day = date.today() - timedelta(days=days - 1)

    screenings_per_day = db.execute(
        text(
            """
            SELECT
              (sr.created_at::date)::text AS day,
              COUNT(*)::int              AS requests
            FROM screening_requests sr
            WHERE sr.created_at::date >= :start_day
            GROUP BY sr.created_at::date
            ORDER BY sr.created_at::date ASC;
            """
        ),
        {"start_day": start_day},
    ).mappings().all()

    screenings_per_day_out = [
        {"day": r["day"], "requests": int(r["requests"])}
        for r in screenings_per_day
    ]

    # Totaux
    total_entities = db.execute(text("SELECT COUNT(*)::int AS n FROM entities;")).mappings().one()["n"]
    total_requests = db.execute(text("SELECT COUNT(*)::int AS n FROM screening_requests;")).mappings().one()["n"]
    total_matches = db.execute(text("SELECT COUNT(*)::int AS n FROM screening_matches;")).mappings().one()["n"]

    return {
        "window_days": days,
        "from_day": str(start_day),
        "totals": {
            "entities": int(total_entities),
            "screening_requests": int(total_requests),
            "screening_matches": int(total_matches),
        },
        "entities_by_source": entities_by_source,
        "entities_by_risk": entities_by_risk_out,
        "screenings_per_day": screenings_per_day_out,
    }