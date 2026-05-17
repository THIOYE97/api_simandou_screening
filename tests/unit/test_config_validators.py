"""Tests pour le validator de config — fail-fast en prod, ergonomie dev."""
from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


def _reload_settings(monkeypatch, **env):
    """Force un reload de app.core.config avec un environnement donné."""
    # Purge l'env existant lié à la config
    for k in (
        "ENVIRONMENT", "SECRET_KEY", "ADMIN_TOKEN",
        "DATABASE_URL", "STORAGE_BACKEND",
        "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)

    for k, v in env.items():
        monkeypatch.setenv(k, v)

    # Reload propre
    import app.core.config as cfg
    return importlib.reload(cfg)


class TestDev:
    def test_dev_no_secret_key_generates_ephemeral(self, monkeypatch):
        cfg = _reload_settings(monkeypatch, ENVIRONMENT="development")
        assert cfg.settings.is_dev
        assert len(cfg.settings.SECRET_KEY) >= 32, "ephemeral key should be generated"

    def test_dev_no_admin_token_generates_ephemeral(self, monkeypatch):
        cfg = _reload_settings(monkeypatch, ENVIRONMENT="development")
        assert cfg.settings.ADMIN_TOKEN.startswith("dev-")
        assert len(cfg.settings.ADMIN_TOKEN) >= 24


class TestProductionFailFast:
    def test_prod_refuses_missing_secret_key(self, monkeypatch):
        with pytest.raises(RuntimeError, match="Insecure configuration"):
            _reload_settings(
                monkeypatch,
                ENVIRONMENT="production",
                SECRET_KEY="",
                ADMIN_TOKEN="x" * 32,
                STORAGE_BACKEND="S3",
                S3_ENDPOINT="https://s3.example.com",
                S3_ACCESS_KEY="k",
                S3_SECRET_KEY="s",
                S3_BUCKET="b",
            )

    def test_prod_refuses_default_secret_key(self, monkeypatch):
        with pytest.raises(RuntimeError):
            _reload_settings(
                monkeypatch,
                ENVIRONMENT="production",
                SECRET_KEY="dev-secret",
                ADMIN_TOKEN="x" * 32,
                STORAGE_BACKEND="S3",
                S3_ENDPOINT="https://s3.example.com",
                S3_ACCESS_KEY="k",
                S3_SECRET_KEY="s",
                S3_BUCKET="b",
            )

    def test_prod_refuses_local_storage(self, monkeypatch):
        with pytest.raises(RuntimeError, match="STORAGE_BACKEND=LOCAL"):
            _reload_settings(
                monkeypatch,
                ENVIRONMENT="production",
                SECRET_KEY="x" * 48,
                ADMIN_TOKEN="x" * 32,
                STORAGE_BACKEND="LOCAL",
            )

    def test_prod_refuses_s3_without_bucket(self, monkeypatch):
        with pytest.raises(RuntimeError, match="S3_BUCKET"):
            _reload_settings(
                monkeypatch,
                ENVIRONMENT="production",
                SECRET_KEY="x" * 48,
                ADMIN_TOKEN="x" * 32,
                STORAGE_BACKEND="S3",
                S3_ENDPOINT="https://s3.example.com",
                S3_ACCESS_KEY="k",
                S3_SECRET_KEY="s",
                # S3_BUCKET intentionally missing
            )

    def test_prod_refuses_default_db_password(self, monkeypatch):
        with pytest.raises(RuntimeError, match="default/example password"):
            _reload_settings(
                monkeypatch,
                ENVIRONMENT="production",
                SECRET_KEY="x" * 48,
                ADMIN_TOKEN="x" * 32,
                DATABASE_URL="postgresql+psycopg://app:postgres@db:5432/x",
                STORAGE_BACKEND="S3",
                S3_ENDPOINT="https://s3.example.com",
                S3_ACCESS_KEY="k",
                S3_SECRET_KEY="s",
                S3_BUCKET="b",
            )

    def test_prod_accepts_valid_config(self, monkeypatch):
        cfg = _reload_settings(
            monkeypatch,
            ENVIRONMENT="production",
            SECRET_KEY="x" * 48,
            ADMIN_TOKEN="x" * 32,
            DATABASE_URL="postgresql+psycopg://app:strong@db.internal:5432/screening",
            STORAGE_BACKEND="S3",
            S3_ENDPOINT="https://s3.example.com",
            S3_ACCESS_KEY="k",
            S3_SECRET_KEY="s",
            S3_BUCKET="b",
            ANTHROPIC_API_KEY="sk-real",
        )
        assert cfg.settings.is_production


class TestCelerySmoothFallback:
    def test_no_broker_means_eager(self, monkeypatch):
        cfg = _reload_settings(monkeypatch, ENVIRONMENT="development")
        assert cfg.settings.celery_eager is True
        assert cfg.settings.cache_enabled is False

    def test_redis_url_activates_celery_and_cache(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        cfg = _reload_settings(monkeypatch, ENVIRONMENT="development")
        assert cfg.settings.celery_eager is False
        assert cfg.settings.cache_enabled is True
        assert cfg.settings.effective_celery_broker == "redis://localhost:6379/0"
