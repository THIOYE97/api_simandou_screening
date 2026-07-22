"""Tests pour le helper de pagination keyset (encode/decode opaques)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.core.pagination import decode_cursor, encode_cursor

pytestmark = pytest.mark.unit


class TestCursorRoundtrip:
    def test_simple_strings(self):
        c = encode_cursor(["a", "b"])
        assert decode_cursor(c) == ["a", "b"]

    def test_with_datetime(self):
        dt = datetime(2026, 5, 17, 12, 30, 0)
        c = encode_cursor([dt, "uuid-1234"])
        decoded = decode_cursor(c)
        assert decoded == [dt.isoformat(), "uuid-1234"]

    def test_with_date(self):
        d = date(2026, 1, 15)
        c = encode_cursor([d, 42])
        decoded = decode_cursor(c)
        assert decoded[0] == d.isoformat()
        assert decoded[1] == 42

    def test_with_ints(self):
        c = encode_cursor([1000, 2000])
        assert decode_cursor(c) == [1000, 2000]


class TestCursorInvalidInputs:
    def test_empty_returns_empty(self):
        assert decode_cursor("") == []

    def test_garbage_returns_empty(self):
        assert decode_cursor("not-base64-at-all!!!") == []

    def test_b64_but_not_json(self):
        # base64 valide, JSON invalide
        import base64
        garbage = base64.urlsafe_b64encode(b"hello world").decode().rstrip("=")
        assert decode_cursor(garbage) == []

    def test_b64_json_but_not_list(self):
        import base64
        import json
        payload = base64.urlsafe_b64encode(json.dumps({"not": "list"}).encode()).decode().rstrip("=")
        assert decode_cursor(payload) == []


class TestCursorOpaqueness:
    """On veut que le format soit opaque côté client : pas de fuite d'info via padding etc."""

    def test_no_trailing_padding(self):
        c = encode_cursor(["x", "y", "z"])
        assert not c.endswith("=")

    def test_urlsafe(self):
        c = encode_cursor(["a" * 100, "b" * 100])
        # Aucun +, /, ou espace
        assert all(ch not in c for ch in "+/= ")
