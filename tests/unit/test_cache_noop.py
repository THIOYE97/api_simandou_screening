"""Tests pour le cache no-op (mode sans Redis)."""
from __future__ import annotations

import pytest

from app.core.cache import _NoopCache, make_key

pytestmark = pytest.mark.unit


class TestNoopCache:
    def test_get_returns_none(self):
        c = _NoopCache()
        assert c.get("anything") is None

    def test_set_does_not_crash(self):
        c = _NoopCache()
        c.set("k", {"v": 1}, ttl=10)  # no-op
        assert c.get("k") is None    # toujours None

    def test_delete_no_op(self):
        c = _NoopCache()
        c.delete("k")

    def test_delete_pattern_returns_zero(self):
        c = _NoopCache()
        assert c.delete_pattern("foo:*") == 0

    def test_health_reports_noop(self):
        h = _NoopCache().health()
        assert h["backend"] == "noop"
        assert h["ok"] is True

    def test_enabled_is_false(self):
        assert _NoopCache().enabled is False


class TestMakeKey:
    def test_short_key_kept_as_is(self):
        k = make_key("matching", "John", "Doe", 42)
        assert k == "matching:John:Doe:42"

    def test_long_key_hashed(self):
        # >120 chars → SHA256
        k = make_key("matching", "a" * 200)
        assert k.startswith("matching:")
        assert len(k) == len("matching:") + 64  # 64 chars hex de sha256

    def test_stable_hash(self):
        k1 = make_key("p", "Hello", 1, 2)
        k2 = make_key("p", "Hello", 1, 2)
        assert k1 == k2

    def test_different_inputs_different_keys(self):
        assert make_key("p", "a") != make_key("p", "b")
