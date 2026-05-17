"""
Tests d'intégration sur le flux d'auth complet :
  login → access token + refresh token → refresh → logout.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


@pytest.fixture
def test_tenant_and_user(db):
    """Crée un tenant + un user actif. Cleanup en sortie."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"{user_id.hex[:8]}@example.com"
    password = "test-pass-12345"

    db.execute(text("RESET ROLE"))
    db.execute(text("SET ROLE auth_bypass_rls"))

    db.execute(
        text("INSERT INTO tenants (id, name, slug, status) VALUES (:tid, :name, :slug, 'ACTIVE')"),
        {"tid": tenant_id, "name": f"tenant-{tenant_id.hex[:6]}", "slug": f"t-{tenant_id.hex[:8]}"},
    )
    db.execute(
        text("""
            INSERT INTO users (id, email, full_name, password_hash, is_active, status, tenant_id)
            VALUES (:uid, :email, 'Test User', :pw, true, 'ACTIVE', :tid)
        """),
        {"uid": user_id, "email": email, "pw": hash_password(password), "tid": tenant_id},
    )
    db.commit()

    yield {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "password": password,
    }

    # Cleanup
    db.execute(text("RESET ROLE"))
    db.execute(text("SET ROLE auth_bypass_rls"))
    db.execute(text("DELETE FROM refresh_tokens WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    db.execute(text("RESET ROLE"))
    db.commit()


class TestLogin:
    def test_login_returns_token_pair(self, client, test_tenant_and_user):
        u = test_tenant_and_user
        r = client.post("/auth/login", json={"email": u["email"], "password": u["password"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert body["refresh_expires_at"]

    def test_login_bad_password(self, client, test_tenant_and_user):
        u = test_tenant_and_user
        r = client.post("/auth/login", json={"email": u["email"], "password": "wrong"})
        assert r.status_code == 401

    def test_login_unknown_user(self, client):
        r = client.post("/auth/login", json={"email": "ghost@example.com", "password": "whatever"})
        assert r.status_code == 401


class TestRefresh:
    def test_refresh_returns_new_pair(self, client, test_tenant_and_user):
        u = test_tenant_and_user
        login = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()

        r = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"]
        assert body["refresh_token"]
        # Avec rotation activée, le nouveau refresh diffère
        assert body["refresh_token"] != login["refresh_token"]

    def test_refresh_old_token_invalidated_after_rotation(self, client, test_tenant_and_user):
        u = test_tenant_and_user
        login = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()

        # Premier refresh OK
        client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
        # Re-utiliser l'ancien doit échouer (token a été rotated/révoqué)
        r2 = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r2.status_code == 401

    def test_refresh_invalid_token(self, client):
        r = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
        assert r.status_code == 401


class TestLogout:
    def test_logout_revokes_refresh_token(self, client, test_tenant_and_user):
        u = test_tenant_and_user
        login = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        r = client.post(
            "/auth/logout",
            json={"refresh_token": login["refresh_token"]},
            headers=headers,
        )
        assert r.status_code == 204

        # Le refresh ne marche plus
        r2 = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r2.status_code == 401

    def test_logout_all_devices(self, client, test_tenant_and_user):
        u = test_tenant_and_user
        # Login 2 fois → 2 refresh tokens actifs
        l1 = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()
        l2 = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()
        headers = {"Authorization": f"Bearer {l2['access_token']}"}

        r = client.post("/auth/logout", json={"all_devices": True}, headers=headers)
        assert r.status_code == 204

        # Les 2 refresh tokens sont morts
        for rt in (l1["refresh_token"], l2["refresh_token"]):
            r2 = client.post("/auth/refresh", json={"refresh_token": rt})
            assert r2.status_code == 401, f"refresh {rt[:10]}... should be revoked"
