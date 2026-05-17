"""
Tests d'isolation RLS multi-tenant.

CRITIQUE: si ces tests cassent, il y a fuite cross-tenant. À surveiller
en CI à chaque PR qui touche les sessions, les routes ou les modèles.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


def _make_user(db, *, email_prefix: str, password: str = "pwd-12345678"):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"{email_prefix}-{user_id.hex[:6]}@example.com"

    db.execute(text("RESET ROLE"))
    db.execute(text("SET ROLE auth_bypass_rls"))
    db.execute(
        text("INSERT INTO tenants (id, name, slug, status) VALUES (:tid, :name, :slug, 'ACTIVE')"),
        {"tid": tenant_id, "name": f"t-{tenant_id.hex[:6]}", "slug": f"t-{tenant_id.hex[:8]}"},
    )
    db.execute(
        text("""
            INSERT INTO users (id, email, full_name, password_hash, is_active, status, tenant_id)
            VALUES (:uid, :email, 'U', :pw, true, 'ACTIVE', :tid)
        """),
        {"uid": user_id, "email": email, "pw": hash_password(password), "tid": tenant_id},
    )
    db.execute(text("RESET ROLE"))
    db.commit()
    return {"tenant_id": str(tenant_id), "user_id": str(user_id), "email": email, "password": password}


def _login(client, user) -> str:
    r = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def two_tenants(db):
    """Crée 2 tenants distincts, chacun avec son user."""
    a = _make_user(db, email_prefix="alpha")
    b = _make_user(db, email_prefix="beta")
    yield {"a": a, "b": b}

    # Cleanup
    db.execute(text("RESET ROLE"))
    db.execute(text("SET ROLE auth_bypass_rls"))
    for u in (a, b):
        db.execute(text("DELETE FROM refresh_tokens WHERE user_id = :uid"), {"uid": u["user_id"]})
        db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": u["user_id"]})
        db.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": u["tenant_id"]})
    db.execute(text("RESET ROLE"))
    db.commit()


class TestTenantIsolation:
    def test_each_tenant_sees_own_cases_only(self, client, db, two_tenants):
        """
        Crée des cases dans 2 tenants, vérifie que chaque user ne voit
        QUE les siens via GET /cases.
        """
        a = two_tenants["a"]
        b = two_tenants["b"]

        # Insérer 2 cases côté tenant A, 3 côté tenant B (via auth_bypass)
        db.execute(text("RESET ROLE"))
        db.execute(text("SET ROLE auth_bypass_rls"))

        # On vérifie d'abord que la table cases a une colonne tenant_id
        has_tenant_col = db.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='cases' AND column_name='tenant_id'
            LIMIT 1
        """)).first()

        if not has_tenant_col:
            pytest.skip("cases.tenant_id missing in this schema — RLS test not applicable")

        # Crée 2 cases pour A, 3 pour B
        for _ in range(2):
            db.execute(text("""
                INSERT INTO cases (case_type, status, created_by, tenant_id)
                VALUES (CAST('KYC' AS case_type), CAST('DRAFT' AS case_status), :uid, :tid)
            """), {"uid": a["user_id"], "tid": a["tenant_id"]})

        for _ in range(3):
            db.execute(text("""
                INSERT INTO cases (case_type, status, created_by, tenant_id)
                VALUES (CAST('KYC' AS case_type), CAST('DRAFT' AS case_status), :uid, :tid)
            """), {"uid": b["user_id"], "tid": b["tenant_id"]})

        db.execute(text("RESET ROLE"))
        db.commit()

        # Login A → doit voir 2
        tok_a = _login(client, a)
        r = client.get("/cases", headers={"Authorization": f"Bearer {tok_a}"})
        assert r.status_code == 200, r.text
        items_a = r.json()["items"]
        assert len(items_a) == 2, f"tenant A should see 2 cases, saw {len(items_a)}"

        # Login B → doit voir 3
        tok_b = _login(client, b)
        r = client.get("/cases", headers={"Authorization": f"Bearer {tok_b}"})
        assert r.status_code == 200
        items_b = r.json()["items"]
        assert len(items_b) == 3, f"tenant B should see 3 cases, saw {len(items_b)}"

        # Aucun chevauchement d'IDs
        ids_a = {c["id"] for c in items_a}
        ids_b = {c["id"] for c in items_b}
        assert ids_a.isdisjoint(ids_b), "case IDs leaked across tenants !"

    def test_protected_route_rejects_missing_token(self, client):
        r = client.get("/cases")
        assert r.status_code == 401

    def test_protected_route_rejects_garbage_token(self, client):
        r = client.get("/cases", headers={"Authorization": "Bearer total-garbage"})
        assert r.status_code == 401
