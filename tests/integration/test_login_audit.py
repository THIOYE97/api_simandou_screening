"""
Tests d'intégration du journal des connexions.

Ce qui est vérifié ici tient en quatre points : une connexion laisse une trace,
un échec aussi, un contexte déjà vu n'est pas signalé deux fois, et la console
de sécurité reste fermée à qui n'est pas super-administrateur.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


def _bypass(db):
    db.execute(text("RESET ROLE"))
    db.execute(text("SET ROLE auth_bypass_rls"))


@pytest.fixture
def compte(db):
    """Un tenant + un compte actif. Le journal est purgé en sortie."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"{user_id.hex[:8]}@example.com"
    password = "test-pass-12345"

    _bypass(db)
    db.execute(
        text("INSERT INTO tenants (id, name, slug, status) VALUES (:tid, :n, :s, 'ACTIVE')"),
        {"tid": tenant_id, "n": f"tenant-{tenant_id.hex[:6]}", "s": f"t-{tenant_id.hex[:8]}"},
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

    _bypass(db)
    db.execute(text("DELETE FROM login_events WHERE user_id = :uid OR email = :e"),
               {"uid": user_id, "e": email})
    db.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM refresh_tokens WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    db.execute(text("RESET ROLE"))
    db.commit()


def _events(db, *, user_id=None, email=None) -> list[dict]:
    _bypass(db)
    clause = "user_id = CAST(:uid AS uuid)" if user_id else "email = :email"
    rows = db.execute(
        text(f"""
            SELECT event, reason, ip, user_agent, is_new_context, tenant_id::text AS tenant_id
            FROM login_events WHERE {clause} ORDER BY created_at
        """),
        {"uid": user_id, "email": email},
    ).mappings().all()
    db.execute(text("RESET ROLE"))
    return [dict(r) for r in rows]


class TestEcriture:
    def test_connexion_reussie_est_journalisee(self, client, compte, db):
        r = client.post("/auth/login", json={"email": compte["email"], "password": compte["password"]})
        assert r.status_code == 200, r.text

        evs = _events(db, user_id=compte["user_id"])
        assert [e["event"] for e in evs] == ["LOGIN_OK"]
        assert evs[0]["tenant_id"] == compte["tenant_id"]
        # Premier accès de ce compte → contexte forcément inconnu.
        assert evs[0]["is_new_context"] is True

    def test_derniere_connexion_reportee_sur_le_compte(self, client, compte, db):
        client.post("/auth/login", json={"email": compte["email"], "password": compte["password"]})

        _bypass(db)
        row = db.execute(
            text("SELECT last_login_at, last_login_ip FROM users WHERE id = CAST(:uid AS uuid)"),
            {"uid": compte["user_id"]},
        ).mappings().first()
        db.execute(text("RESET ROLE"))
        assert row["last_login_at"] is not None

    def test_second_acces_meme_contexte_non_signale(self, client, compte, db):
        for _ in range(2):
            client.post("/auth/login", json={"email": compte["email"], "password": compte["password"]})

        evs = [e for e in _events(db, user_id=compte["user_id"]) if e["event"] == "LOGIN_OK"]
        assert len(evs) == 2
        assert evs[0]["is_new_context"] is True
        assert evs[1]["is_new_context"] is False, "même IP et même appareil : rien de nouveau"

    def test_mauvais_mot_de_passe_journalise(self, client, compte, db):
        r = client.post("/auth/login", json={"email": compte["email"], "password": "faux"})
        assert r.status_code == 401

        evs = _events(db, user_id=compte["user_id"])
        assert [(e["event"], e["reason"]) for e in evs] == [("LOGIN_FAILED", "bad_password")]

    def test_adresse_inconnue_journalisee_sans_compte(self, client, db):
        inconnu = f"fantome-{uuid.uuid4().hex[:8]}@example.com"
        r = client.post("/auth/login", json={"email": inconnu, "password": "peu importe"})
        assert r.status_code == 401

        evs = _events(db, email=inconnu)
        assert [(e["event"], e["reason"]) for e in evs] == [("LOGIN_FAILED", "unknown_user")]

        _bypass(db)
        db.execute(text("DELETE FROM login_events WHERE email = :e"), {"e": inconnu})
        db.execute(text("RESET ROLE"))
        db.commit()

    def test_deconnexion_journalisee(self, client, compte, db):
        login = client.post(
            "/auth/login", json={"email": compte["email"], "password": compte["password"]}
        ).json()
        r = client.post(
            "/auth/logout",
            json={"refresh_token": login["refresh_token"]},
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
        assert r.status_code == 204

        evs = _events(db, user_id=compte["user_id"])
        assert [e["event"] for e in evs] == ["LOGIN_OK", "LOGOUT"]


class TestConsoleDeSecurite:
    def _token(self, client, compte) -> str:
        return client.post(
            "/auth/login", json={"email": compte["email"], "password": compte["password"]}
        ).json()["access_token"]

    def test_refus_sans_super_admin(self, client, compte):
        tok = self._token(client, compte)
        for url in ("/security/login-events", "/security/sessions",
                    "/security/login-summary", "/security/accounts"):
            r = client.get(url, headers={"Authorization": f"Bearer {tok}"})
            assert r.status_code == 403, f"{url} devrait être fermé : {r.status_code}"

    def test_refus_sans_jeton(self, client):
        assert client.get("/security/login-events").status_code == 401

    def test_super_admin_lit_le_journal(self, client, compte, db):
        # Le rôle structurel SUPER_ADMIN est ce que lit l'émission du jeton.
        _bypass(db)
        db.execute(
            text("""
                INSERT INTO user_roles (id, tenant_id, user_id, role)
                VALUES (gen_random_uuid(), CAST(:tid AS uuid), CAST(:uid AS uuid), 'SUPER_ADMIN')
            """),
            {"tid": compte["tenant_id"], "uid": compte["user_id"]},
        )
        db.execute(text("RESET ROLE"))
        db.commit()

        tok = self._token(client, compte)
        entetes = {"Authorization": f"Bearer {tok}"}

        r = client.get("/security/login-events", headers=entetes)
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["total"] >= 1
        assert any(e["email"] == compte["email"] for e in corps["items"])

        s = client.get("/security/login-summary", headers=entetes)
        assert s.status_code == 200
        assert s.json()["logins_24h"] >= 1

        sess = client.get("/security/sessions", headers=entetes)
        assert sess.status_code == 200
        assert any(x["email"] == compte["email"] for x in sess.json()["items"])

        acc = client.get("/security/accounts", headers=entetes)
        assert acc.status_code == 200
        moi = [x for x in acc.json()["items"] if x["email"] == compte["email"]]
        assert moi and moi[0]["last_login_at"] is not None

    def test_filtre_par_evenement(self, client, compte, db):
        _bypass(db)
        db.execute(
            text("""
                INSERT INTO user_roles (id, tenant_id, user_id, role)
                VALUES (gen_random_uuid(), CAST(:tid AS uuid), CAST(:uid AS uuid), 'SUPER_ADMIN')
            """),
            {"tid": compte["tenant_id"], "uid": compte["user_id"]},
        )
        db.execute(text("RESET ROLE"))
        db.commit()

        client.post("/auth/login", json={"email": compte["email"], "password": "faux"})
        tok = self._token(client, compte)

        r = client.get(
            "/security/login-events?event=LOGIN_FAILED&limit=50",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200
        assert all(e["event"] == "LOGIN_FAILED" for e in r.json()["items"])

        mauvais = client.get(
            "/security/login-events?event=NIMPORTE_QUOI",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert mauvais.status_code == 422
