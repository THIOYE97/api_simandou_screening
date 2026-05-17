# app/core/pagination.py
"""
Pagination keyset (curseur) — résistante à la profondeur.

Pourquoi keyset > offset :
- offset 100_000 force Postgres à scanner et jeter 100k lignes → O(N), très lent
- keyset compare directement sur l'index ordonné → O(log N)

Usage :
    page = keyset_paginate(
        db,
        base_query=select(Case).where(Case.tenant_id == tid),
        order_by=[Case.created_at.desc(), Case.id.desc()],
        limit=50,
        cursor=req.cursor,   # str ou None
    )
    return {
        "items":       page.items,
        "next_cursor": page.next_cursor,
        "has_more":    page.has_more,
    }

Le curseur est un blob base64 opaque côté client. Côté serveur, il encode
la dernière clé d'ordre vue (typiquement (created_at, id)).

Fallback compat : si le client envoie `offset=N`, on l'accepte mais on log
un warning de dépréciation.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional, Sequence

from sqlalchemy import Select, and_, or_, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import UnaryExpression

from app.core.logging import get_logger

logger = get_logger("simandou.pagination")

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


@dataclass(frozen=True)
class Page:
    items: list[Any]
    next_cursor: Optional[str]
    has_more: bool


# --- Cursor encode/decode ---------------------------------------------------

def _serialize(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _deserialize_for(col, raw: Any) -> Any:
    """Coerce un cursor field selon le type de colonne."""
    if raw is None:
        return None
    t = getattr(col.type, "python_type", None)
    try:
        if t is datetime and isinstance(raw, str):
            return datetime.fromisoformat(raw)
        if t is date and isinstance(raw, str):
            return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return raw
    return raw


def encode_cursor(values: Sequence[Any]) -> str:
    payload = json.dumps([_serialize(v) for v in values], default=str)
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> list[Any]:
    if not cursor:
        return []
    try:
        pad = "=" * (-len(cursor) % 4)
        payload = base64.urlsafe_b64decode(cursor + pad).decode()
        data = json.loads(payload)
        if not isinstance(data, list):
            raise ValueError("cursor payload must be a list")
        return data
    except Exception as e:
        logger.info("invalid_cursor", extra={"err": str(e)})
        return []


# --- Core ------------------------------------------------------------------

def keyset_paginate(
    db: Session,
    *,
    base_query: Select,
    order_by: list[UnaryExpression],
    limit: int = DEFAULT_LIMIT,
    cursor: Optional[str] = None,
) -> Page:
    """
    Paginate via keyset.

    Args:
        base_query : Select de base (avec ses where, sans order_by/limit)
        order_by   : ex. [Case.created_at.desc(), Case.id.desc()]
                     Le dernier doit être un tiebreaker unique (clé primaire).
        limit      : taille de page (clamped à MAX_LIMIT)
        cursor     : opaque b64 du précédent next_cursor
    """
    limit = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))

    # Extraire les colonnes effectives des order_by (UnaryExpression.element)
    cols = []
    descs = []
    for ob in order_by:
        # UnaryExpression a .element ; un Column nu n'en a pas
        elem = getattr(ob, "element", ob)
        modifier = getattr(ob, "modifier", None)
        descs.append(bool(modifier) and "desc" in str(modifier).lower())
        cols.append(elem)

    query = base_query.order_by(*order_by).limit(limit + 1)

    if cursor:
        decoded = decode_cursor(cursor)
        if decoded and len(decoded) == len(cols):
            coerced = [_deserialize_for(cols[i], decoded[i]) for i in range(len(cols))]

            # Construction du WHERE keyset : (col1, col2, …) < (v1, v2, …)
            # mais en respectant l'ordre desc/asc de chaque colonne.
            # Cas simple : tous DESC ou tous ASC → tuple compare direct.
            if all(descs):
                query = query.where(tuple_(*cols) < tuple_(*coerced))
            elif not any(descs):
                query = query.where(tuple_(*cols) > tuple_(*coerced))
            else:
                # Cas mixte : on déroule en ladder OR/AND (correct pour n=2)
                clauses = []
                for i in range(len(cols)):
                    parts = []
                    for j in range(i):
                        parts.append(cols[j] == coerced[j])
                    op = (cols[i] < coerced[i]) if descs[i] else (cols[i] > coerced[i])
                    parts.append(op)
                    clauses.append(and_(*parts))
                query = query.where(or_(*clauses))

    rows = db.execute(query).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_more and items:
        last = items[-1]
        key_values = [getattr(last, c.name if hasattr(c, "name") else c.key) for c in cols]
        next_cursor = encode_cursor(key_values)

    return Page(items=list(items), next_cursor=next_cursor, has_more=has_more)
