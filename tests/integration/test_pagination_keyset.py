"""
Test d'intégration : keyset pagination sur /cases.

On crée N cases puis on les pagine. Garanties :
  - Pas de doublon entre 2 pages
  - Couverture exhaustive (sum des pages == N)
  - Cursor opaque côté client
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


@pytest.fixture
def tenant_with_cases(db, request):
    """Tenant + user + N cases (N défini par paramètre indirect)."""
    n = getattr(request, "param", 25)

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"page-{user_id.hex[:6]}@example.com"
    password = "test-pass-12345"

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

    has_tenant_col = db.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='cases' AND column_name='tenant_id'
        LIMIT 1
    """)).first()
    if not has_tenant_col:
        db.execute(text("RESET ROLE"))
        db.commit()
        pytest.skip("cases.tenant_id missing — keyset test not applicable to current schema")

    for _ in range(n):
        db.execute(text("""
            INSERT INTO cases (case_type, status, created_by, tenant_id)
            VALUES (CAST('KYC' AS case_type), CAST('DRAFT' AS case_status), :uid, :tid)
        """), {"uid": user_id, "tid": tenant_id})

    db.execute(text("RESET ROLE"))
    db.commit()

    yield {"email": email, "password": password, "n": n, "tenant_id": str(tenant_id), "user_id": str(user_id)}

    db.execute(text("RESET ROLE"))
    db.execute(text("SET ROLE auth_bypass_rls"))
    db.execute(text("DELETE FROM cases WHERE tenant_id = :tid"), {"tid": tenant_id})
    db.execute(text("DELETE FROM refresh_tokens WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    db.execute(text("RESET ROLE"))
    db.commit()


@pytest.mark.parametrize("tenant_with_cases", [25], indirect=True)
def test_pagination_walks_all_items_without_duplicates(client, tenant_with_cases):
    u = tenant_with_cases
    login = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    seen_ids: set[str] = set()
    cursor = None
    page_count = 0
    while True:
        params = {"limit": 10}
        if cursor:
            params["cursor"] = cursor

        r = client.get("/cases", params=params, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        page_ids = {it["id"] for it in body["items"]}

        # Pas de doublon entre pages
        assert page_ids.isdisjoint(seen_ids), "duplicates across pages"

        seen_ids |= page_ids
        page_count += 1

        if not body["has_more"]:
            break
        cursor = body["next_cursor"]
        assert cursor, "has_more=True but next_cursor is empty"

        if page_count > 10:
            pytest.fail("infinite loop in keyset pagination")

    assert len(seen_ids) == u["n"], f"expected {u['n']} ids, got {len(seen_ids)}"
    assert page_count >= 3, "with 25 items and limit=10 we expect at least 3 pages"


@pytest.mark.parametrize("tenant_with_cases", [3], indirect=True)
def test_pagination_under_limit_single_page(client, tenant_with_cases):
    u = tenant_with_cases
    login = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    r = client.get("/cases", params={"limit": 50}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == u["n"]
    assert body["has_more"] is False
    assert body["next_cursor"] is None


@pytest.mark.parametrize("tenant_with_cases", [5], indirect=True)
def test_pagination_invalid_cursor_starts_from_beginning(client, tenant_with_cases):
    u = tenant_with_cases
    login = client.post("/auth/login", json={"email": u["email"], "password": u["password"]}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    # Cursor pourri → la décode retourne [] → on doit obtenir la 1re page (5 items)
    r = client.get(
        "/cases",
        params={"limit": 50, "cursor": "totally-garbage-cursor"},
        headers=headers,
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == u["n"]
