"""
Conftest global — fixtures partagées.

Tests unitaires : aucune dépendance externe.
Tests d'intégration : Postgres jetable via testcontainers (Docker requis).
"""
from __future__ import annotations

import os
import secrets
import sys

import pytest

# ----------------------------------------------------------------------------
# Settings d'environnement IMPÉRATIFS avant le moindre import `app.*`.
# Sinon le validator de config peut crasher (en prod) ou consommer une vraie
# clé Anthropic.
# ----------------------------------------------------------------------------

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("ADMIN_TOKEN", secrets.token_urlsafe(32))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-real")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")  # désactive pour tests
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")


# ----------------------------------------------------------------------------
# Integration: Postgres jetable
# ----------------------------------------------------------------------------

def _pytest_collection_modifyitems_skip_integration_if_no_docker(config, items):
    """
    Si Docker n'est pas dispo, skip tous les tests `integration` avec un message
    propre plutôt que d'exploser à la première fixture.
    """
    try:
        import docker  # type: ignore
        client = docker.from_env()
        client.ping()
        docker_ok = True
    except Exception:
        docker_ok = False

    if docker_ok:
        return

    skip_marker = pytest.mark.skip(reason="Docker not available — skipping integration tests")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


def pytest_collection_modifyitems(config, items):
    _pytest_collection_modifyitems_skip_integration_if_no_docker(config, items)


@pytest.fixture(scope="session")
def pg_container():
    """Spawn un Postgres jetable. Partagé par toute la session pytest."""
    from testcontainers.postgres import PostgresContainer

    pg = PostgresContainer(
        image="postgres:16",
        username="test",
        password="test",
        dbname="test",
    )
    pg.start()
    try:
        yield pg
    finally:
        pg.stop()


@pytest.fixture(scope="session")
def database_url(pg_container) -> str:
    """URL Postgres testcontainer, adaptée pour psycopg3 + SQLAlchemy."""
    raw = pg_container.get_connection_url()
    # testcontainers renvoie "postgresql+psycopg2://..." — on force psycopg3
    return raw.replace("postgresql+psycopg2://", "postgresql+psycopg://")


@pytest.fixture(scope="session")
def migrated_db(database_url):
    """
    Bootstrap la DB testcontainer pour les tests d'intégration.

    NB: on n'utilise PAS `alembic upgrade head` car l'historique Alembic
    actuel a un double-baseline qui crée des conflits sur DB vierge
    (cf. REFACTOR.md §2). On crée le schéma via Base.metadata, ce qui :
      - reflète exactement l'état des modèles SQLAlchemy
      - est rapide
      - testera quand même tous les flux applicatifs
    Le test des migrations elles-mêmes est un concern séparé.
    """
    os.environ["DATABASE_URL"] = database_url

    # Reload des modules qui ont déjà importé settings (sinon ils gardent l'ancienne URL)
    for mod_name in list(sys.modules):
        if mod_name.startswith("app."):
            sys.modules.pop(mod_name, None)

    from sqlalchemy import create_engine, text

    eng = create_engine(database_url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        # Le rôle auth_bypass_rls est utilisé par le code applicatif
        conn.execute(text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='auth_bypass_rls') THEN "
            "    CREATE ROLE auth_bypass_rls; "
            "  END IF; "
            "END $$;"
        ))

        # Les modèles utilisent `create_type=False` car en prod les types ENUM
        # existent déjà. En test, on doit les créer manuellement avant create_all.
        # Si on en ajoute en prod, dupliquer ici.
        enum_definitions = [
            ("case_type", ["KYC", "KYB"]),
            ("case_status", ["DRAFT", "PENDING_REVIEW", "ACTION_REQUIRED", "APPROVED", "REJECTED"]),
            ("risk_level", ["LOW", "MEDIUM", "HIGH"]),
            ("entity_type", ["person", "company"]),
            ("record_type", ["SANCTION", "PEP", "ADVERSE_MEDIA", "BAN"]),
            ("match_band", ["STRONG", "POSSIBLE", "WEAK"]),
            ("action_type", ["PASS", "MANUAL_REVIEW", "BLOCK"]),
            ("ocr_status", ["PENDING", "DONE", "FAILED", "LOW_CONFIDENCE"]),
            ("company_role_type", ["BENEFICIAL_OWNER", "DIRECTOR", "REPRESENTATIVE", "SHAREHOLDER", "OTHER"]),
        ]
        for name, values in enum_definitions:
            vals_sql = ", ".join(f"'{v}'" for v in values)
            conn.execute(text(
                f"DO $$ BEGIN "
                f"  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='{name}') THEN "
                f"    CREATE TYPE {name} AS ENUM ({vals_sql}); "
                f"  END IF; "
                f"END $$;"
            ))

    # Charge TOUS les modèles avant create_all
    from app.models import load_all_models
    from app.models.base import Base

    load_all_models()

    # Crée toutes les tables / types ENUM à partir des modèles SQLAlchemy
    Base.metadata.create_all(eng)

    # Grants pour le rôle bypass-RLS (utilisé par le service auth)
    with eng.begin() as conn:
        conn.execute(text("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO test"))
        conn.execute(text("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO auth_bypass_rls"))
        conn.execute(text("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO auth_bypass_rls"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO auth_bypass_rls"))

    yield database_url

    eng.dispose()


@pytest.fixture
def db(migrated_db):
    """
    Session DB liée à la DB migrée. Rollback en fin de test pour isolation.
    """
    from app.core.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(migrated_db):
    """TestClient FastAPI. Le boot s'appuie sur la DATABASE_URL du testcontainer."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c
