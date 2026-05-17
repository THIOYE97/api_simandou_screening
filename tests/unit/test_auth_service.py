"""Tests pour les fonctions pures du service auth (hash, password, JWT)."""
from __future__ import annotations

import pytest

from app.services.auth_service import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

pytestmark = pytest.mark.unit


class TestPasswordHashing:
    def test_argon2_is_default(self):
        h = hash_password("supersecret123")
        assert h.startswith("$argon2")

    def test_verify_argon2_roundtrip(self):
        h = hash_password("supersecret123")
        assert verify_password("supersecret123", h)

    def test_verify_argon2_wrong_password(self):
        h = hash_password("supersecret123")
        assert not verify_password("wrong", h)

    def test_bcrypt_compat(self):
        h = hash_password("supersecret123", algo="bcrypt")
        assert h.startswith("$2")
        assert verify_password("supersecret123", h)
        assert not verify_password("wrong", h)

    def test_rejects_short_password(self):
        with pytest.raises(ValueError, match="too short"):
            hash_password("short")

    def test_verify_empty_inputs(self):
        assert not verify_password("", "")
        assert not verify_password("pwd", "")
        assert not verify_password("", "$argon2id$v=19$m=102400,t=2,p=8$x$y")

    def test_verify_garbage_hash(self):
        # Doesn't crash, returns False
        assert not verify_password("any", "not-a-real-hash")


class TestRefreshTokenHash:
    def test_sha256_64_chars(self):
        h = hash_refresh_token("my-token")
        assert len(h) == 64
        # All hex
        int(h, 16)

    def test_stable(self):
        assert hash_refresh_token("x") == hash_refresh_token("x")

    def test_differs_per_input(self):
        assert hash_refresh_token("a") != hash_refresh_token("b")


class TestAccessToken:
    def test_encode_decode_roundtrip(self):
        token = create_access_token(
            {"sub": "user-1", "tenant_id": "tenant-1", "is_super_admin": False}
        )
        payload = decode_access_token(token)
        assert payload["sub"] == "user-1"
        assert payload["tenant_id"] == "tenant-1"
        assert payload["is_super_admin"] is False
        assert "exp" in payload
        assert "iat" in payload

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError, match="Invalid token"):
            decode_access_token("not.a.jwt")

    def test_tampered_token_raises(self):
        token = create_access_token({"sub": "u", "tenant_id": "t"})
        # Modifier 1 caractère doit casser la signature
        tampered = token[:-2] + ("XX" if token[-2:] != "XX" else "YY")
        with pytest.raises(ValueError):
            decode_access_token(tampered)
