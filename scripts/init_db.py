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

# Révision Alembic que représente le schéma canonique. Déterminée par
# comparaison : le schéma contient `compliance_events` (m6b) mais l'énumération
# `alert_status` y porte encore ses anciennes valeurs, donc il précède m6d.
# À mettre à jour si le fichier db/baseline_schema.sql est régénéré.
BASELINE_REVISION = "m6b_compliance_audit"

# Tables introduites par des migrations POSTÉRIEURES au schéma canonique. Leur
# présence atteste que la montée de version a bien eu lieu.
POST_BASELINE_TABLES = (
    "ubo_declarations", "ubo_documents", "offshore_records",
    "offshore_relations", "press_search_cache",
)

APP_ROLE = "screening_app"
BYPASS_ROLE = "auth_bypass_rls"


_DOLLAR_TAG = re.compile(r"\$[A-Za-z_0-9]*\$")


def _split_sql(sql: str) -> list[str]:
    """Découpe un script pg_dump en instructions exécutables.

    Petit lexer : il neutralise les `;` qui n'ont pas valeur de terminateur —
    ceux nichés dans les commentaires `-- …`, les chaînes `'…'` et les blocs
    dollar-quote `$tag$…$tag$`. Sans cela, une ligne d'en-tête pg_dump comme
    `-- Name: x; Type: TABLE; Schema: public; Owner: -` était éclatée en
    fragments (`Type: TABLE`…) envoyés tels quels à PostgreSQL, faisant échouer
    tout le chargement du schéma canonique.
    """
    stmts, buf, i, n = [], [], 0, len(sql)
    while i < n:
        ch = sql[i]
        # commentaire ligne : on saute jusqu'au saut de ligne inclus
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        # chaîne littérale : un ';' n'y termine rien (les '' échappés se gèrent
        # par bascule successive)
        if ch == "'":
            buf.append(ch); i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == "'":
                    i += 1; break
                i += 1
            continue
        # bloc dollar-quote : $$…$$ ou $tag$…$tag$
        if ch == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                tag = m.group(0)
                end = sql.find(tag, m.end())
                end = n if end == -1 else end + len(tag)
                buf.append(sql[i:end]); i = end; continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []; i += 1; continue
        buf.append(ch); i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    # retire le bruit pg_dump résiduel (SET …, SELECT pg_catalog.set_config…,
    # \connect, COMMENT ON EXTENSION) et les instructions vidées de tout contenu
    out = []
    for s in stmts:
        # une instruction réduite à des lignes de commentaire est sans effet
        body = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("--")).strip()
        if not body:
            continue
        # méta-commandes psql (\restrict, \unrestrict, \connect… — PG 17+)
        if body.startswith("\\"):
            continue
        first = body.split("\n", 1)[0].upper()
        if first.startswith(("SET ", "SELECT PG_CATALOG", "COMMENT ON EXTENSION")):
            continue
        out.append(body)
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
            # L'utilisateur de connexion (propriétaire Render, non-superuser)
            # doit être MEMBRE du rôle pour pouvoir `SET ROLE` dessus lors du
            # seed. En dev local la connexion est superuser, ce qui masquait
            # l'absence de cette appartenance : le seed échouait alors sur
            # « permission denied to set role » à la première reconstruction.
            c.execute(text(f"GRANT {role} TO CURRENT_USER"))
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
            # pg_dump crée des fonctions qui référencent des tables définies plus
            # loin dans le fichier ; il pose pour cela `check_function_bodies` à
            # false. Le filtre anti-bruit écartant les `SET`, on le repose ici,
            # sans quoi get_user_for_login (utilisée par /auth/login) échoue.
            c.execute(text("SET check_function_bodies = false"))
            for s in stmts:
                try:
                    c.execute(text(s))
                except Exception as e:
                    # tolère les objets déjà existants (idempotence)
                    if not re.search(r"already exists|existe déjà", str(e)):
                        print(f"⚠ échec sur : {s[:80]}…\n  {str(e)[:160]}", file=sys.stderr)
        print(f"✓ schéma appliqué ({len(stmts)} instructions)")

    # 3) calage Alembic puis montée jusqu'à la tête -------------------------
    #
    # On cale sur la révision que REPRÉSENTE le schéma canonique, puis on
    # applique les migrations suivantes. Caler directement sur la tête
    # déclarerait appliquées des migrations dont les tables n'existent pas :
    # une base neuve démarrerait alors sans `ubo_declarations`,
    # `offshore_records`, `offshore_relations` ni `press_search_cache`, et
    # Alembic la dirait à jour. L'anomalie ne se verrait qu'à l'usage.
    env = {**os.environ, "DATABASE_URL": url}

    def _alembic(*args) -> bool:
        r = subprocess.run([sys.executable, "-m", "alembic", *args], env=env,
                           cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠ alembic {' '.join(args)} : {r.stderr[-300:]}", file=sys.stderr)
        return r.returncode == 0

    if _alembic("stamp", BASELINE_REVISION):
        print(f"✓ alembic stamp {BASELINE_REVISION}")
    if _alembic("upgrade", "head"):
        print("✓ alembic upgrade head")

    # Contrôle : les tables introduites APRÈS le schéma canonique doivent
    # exister. Sans ce garde-fou, une base incomplète se présenterait comme
    # saine — c'est précisément ce qui rendait toute reconstruction illusoire.
    with eng.begin() as c:
        manquantes = [t for t in POST_BASELINE_TABLES if not c.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t"), {"t": t}).scalar()]
    if manquantes:
        print(f"✗ tables absentes après migration : {', '.join(manquantes)}", file=sys.stderr)
        return 1
    print("✓ schéma complet vérifié")

    # 3b) privilèges runtime + contournement RLS du rôle de bypass ----------
    #
    # Le dump canonique est produit sans privilèges (pg_dump --no-privileges) :
    # les rôles applicatifs n'héritent donc d'AUCUN droit sur les tables. On
    # les accorde ici. Point critique : /auth/login lit `users` sous
    # `SET ROLE auth_bypass_rls`, AVANT de connaître le tenant — ce rôle doit
    # donc contourner l'isolation par tenant. L'attribut BYPASSRLS n'est pas
    # posable sur une base Render (propriétaire non-superuser), mais le
    # propriétaire des tables PEUT créer une politique permissive équivalente.
    # Sans ce bloc, toute base reconstruite renvoie « permission denied for
    # table users » puis, une fois les droits posés, un 401 systématique.
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}, {BYPASS_ROLE}"))
        for role in (APP_ROLE, BYPASS_ROLE):
            c.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"))
            c.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))
            c.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"))
            c.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}"))
        rls_tables = [r[0] for r in c.execute(text(
            "SELECT relname FROM pg_class "
            "WHERE relrowsecurity AND relnamespace = 'public'::regnamespace ORDER BY relname"))]
        for t in rls_tables:
            c.execute(text(f'DROP POLICY IF EXISTS bypass_all ON public."{t}"'))
            c.execute(text(f'CREATE POLICY bypass_all ON public."{t}" '
                           f'TO {BYPASS_ROLE} USING (true) WITH CHECK (true)'))
    print(f"✓ privilèges rôles + contournement RLS ({len(rls_tables)} table(s))")

    # 4) seed référentiel + admin ------------------------------------------
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.services import (
        adverse_media_service, alerting_service, rbac_service, referentiel_service,
    )
    from app.services.auth_service import hash_password

    # On sème en tant que propriétaire de connexion — exactement le modèle du
    # runtime (app/core/db.py se connecte propriétaire, fait RESET ROLE et
    # isole par GUC app.tenant_id). Le propriétaire contourne la RLS ENABLE
    # (seule `cases` est en FORCE, non touchée ici). L'ancien
    # `SET ROLE auth_bypass_rls` ne fonctionnait que sous une connexion
    # superuser locale : sur une base Render (propriétaire non-superuser) il
    # échouait — d'abord faute d'appartenance au rôle, puis faute de privilège.
    with eng.begin() as c:
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
