#!/usr/bin/env python
"""
Initialisation reproductible d'une base VIERGE (ex. Railway).

Idempotent : peut être relancé sans risque.
  1. crée les rôles requis (screening_app, auth_bypass_rls) ;
  2. crée les extensions (pgcrypto, pg_trgm, unaccent, uuid-ossp) ;
  3. applique le schéma canonique (db/baseline_schema.sql) si la base est vide ;
  4. cale Alembic sur la tête (stamp head) — les migrations futures s'empilent dessus ;
  5. seed le référentiel LBC/FT + un compte administrateur initial.

Usage :
    DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db \
    ADMIN_EMAIL=admin@bcrg-guinee.org ADMIN_PASSWORD='ChangeMoi123' \
    python -m scripts.init_db
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "db" / "baseline_schema.sql"

APP_ROLE = "screening_app"
BYPASS_ROLE = "auth_bypass_rls"


def _split_sql(sql: str) -> list[str]:
    """Découpe un script SQL en instructions, en respectant les blocs $$…$$."""
    stmts, buf, i, in_dollar, tag = [], [], 0, False, ""
    while i < len(sql):
        ch = sql[i]
        if not in_dollar and sql.startswith("$$", i):
            in_dollar, tag = True, "$$"
            buf.append("$$"); i += 2; continue
        if in_dollar and sql.startswith(tag, i):
            in_dollar = False
            buf.append(tag); i += len(tag); continue
        if ch == ";" and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []; i += 1; continue
        buf.append(ch); i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    # retire le bruit pg_dump (SET …, SELECT pg_catalog.set_config…, \connect)
    out = []
    for s in stmts:
        first = s.lstrip().split("\n", 1)[0].upper()
        if first.startswith(("SET ", "SELECT PG_CATALOG", "\\CONNECT", "COMMENT ON EXTENSION")):
            continue
        out.append(s)
    return out


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL manquant.", file=sys.stderr)
        return 2
    admin_email = os.getenv("ADMIN_EMAIL", "admin@bcrg-guinee.org")
    admin_password = os.getenv("ADMIN_PASSWORD", "Simandou2026")

    eng = create_engine(url)

    # 1) rôles + extensions -------------------------------------------------
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for role in (APP_ROLE, BYPASS_ROLE):
            c.execute(text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$;"
            ))
        for ext in ("pgcrypto", "pg_trgm", "unaccent", '"uuid-ossp"'):
            c.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
    print("✓ rôles + extensions")

    # 2) schéma (si base vide) ---------------------------------------------
    with eng.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='users'"
        )).scalar()
    if n:
        print("• schéma déjà présent — application du schéma ignorée")
    else:
        if not BASELINE.exists():
            print(f"Baseline introuvable : {BASELINE}", file=sys.stderr)
            return 2
        sql = BASELINE.read_text()
        stmts = _split_sql(sql)
        with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            for s in stmts:
                try:
                    c.execute(text(s))
                except Exception as e:
                    # tolère les objets déjà existants (idempotence)
                    if not re.search(r"already exists|existe déjà", str(e)):
                        print(f"⚠ échec sur : {s[:80]}…\n  {str(e)[:160]}", file=sys.stderr)
        print(f"✓ schéma appliqué ({len(stmts)} instructions)")

    # 3) alembic stamp head -------------------------------------------------
    env = {**os.environ, "DATABASE_URL": url}
    r = subprocess.run([sys.executable, "-m", "alembic", "stamp", "head"], env=env,
                       cwd=str(ROOT), capture_output=True, text=True)
    print("✓ alembic stamp head" if r.returncode == 0 else f"⚠ alembic stamp: {r.stderr[-200:]}")

    # 4) seed référentiel + admin ------------------------------------------
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.services import (
        adverse_media_service, alerting_service, rbac_service, referentiel_service,
    )
    from app.services.auth_service import hash_password

    with eng.begin() as c:
        c.execute(text(f"SET ROLE {BYPASS_ROLE}"))
        tid = c.execute(text("SELECT id FROM tenants WHERE slug='bcrg' LIMIT 1")).scalar()
        if not tid:
            tid = uuid.uuid4()
            c.execute(text("INSERT INTO tenants (id,name,slug,status) VALUES (:i,'BCRG','bcrg','ACTIVE')"),
                      {"i": str(tid)})
        uid = c.execute(text("SELECT id FROM users WHERE email=:e"), {"e": admin_email}).scalar()
        if not uid:
            uid = uuid.uuid4()
            c.execute(text(
                "INSERT INTO users (id,email,full_name,password_hash,is_active,status,tenant_id) "
                "VALUES (:i,:e,'Administrateur BCRG',:p,true,'ACTIVE',:t)"),
                {"i": str(uid), "e": admin_email, "p": hash_password(admin_password), "t": str(tid)})
        c.execute(text("RESET ROLE"))

    db = SessionLocal()
    try:
        rbac_service.seed_roles(db)
        # table d'affectation RBAC (non couverte par les policies legacy)
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS rbac_user_roles ("
            "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id UUID NOT NULL, "
            "user_id UUID NOT NULL, role_code VARCHAR(32) NOT NULL, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "CONSTRAINT uq_rbac_user_roles UNIQUE (tenant_id, user_id, role_code))"))
        db.commit()
        rbac_service.assign_role(db, uid, tid, "OWNER")
        referentiel_service.seed_referentiel(db)
        alerting_service.seed_rules(db)
        adverse_media_service.seed_adverse_media(db)
    finally:
        db.close()
    print(f"✓ seed terminé — admin : {admin_email}")
    print(f"  storage backend : {settings.STORAGE_BACKEND}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
