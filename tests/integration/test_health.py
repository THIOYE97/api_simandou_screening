"""Tests d'intégration sur les endpoints de health/readyz."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_liveness_always_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_healthz_alias(client):
    r = client.get("/healthz")
    assert r.status_code == 200


def test_readyz_ok_when_db_reachable(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["checks"]["db"] == "ok"


def test_request_id_header_round_trip(client):
    """Le middleware doit accepter un X-Request-Id et le renvoyer."""
    r = client.get("/health", headers={"X-Request-Id": "test-rid-123"})
    assert r.status_code == 200
    assert r.headers.get("x-request-id") == "test-rid-123"


def test_request_id_generated_if_absent(client):
    r = client.get("/health")
    assert r.status_code == 200
    rid = r.headers.get("x-request-id")
    assert rid and len(rid) >= 16
