# app/core/config.py
from __future__ import annotations

import logging
import secrets
import sys
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("simandou.config")

Environment = Literal["development", "staging", "production"]

_INSECURE_SECRETS = {"", "dev-secret", "change-me", "changeme", "secret", "dev-admin-token"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- Environment -------------------------------------------------------
    ENVIRONMENT: Environment = "production"

    # ---- DB ----------------------------------------------------------------
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_POOL_TIMEOUT_SECONDS: int = 10
    DB_DISABLE_PREPARED_STATEMENTS: bool = False  # set True if behind pgbouncer transaction mode

    # ---- Auth --------------------------------------------------------------
    SECRET_KEY: str = ""
    ADMIN_TOKEN: str = ""
    ALGORITHM: str = "HS256"
    # S3 : access tokens courts + refresh tokens longs
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30           # 30 min (avant: 5 jours)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30             # 30 jours
    REFRESH_TOKEN_ROTATION: bool = True             # nouveau refresh à chaque /refresh

    AUTH_BYPASS_ROLE: str = "auth_bypass_rls"

    # ---- Storage -----------------------------------------------------------
    STORAGE_BACKEND: Literal["LOCAL", "S3"] = "LOCAL"
    LOCAL_STORAGE_ROOT: str = "storage"
    PRESIGNED_URL_TTL_SECONDS: int = 300

    # ---- SUMSUB ------------------------------------------------------------
    SUMSUB_BASE_URL: str = "https://api.sumsub.com"
    SUMSUB_APP_TOKEN: str = ""
    SUMSUB_SECRET_KEY: str = ""
    SUMSUB_LEVEL_NAME: str = "basic-kyc"
    SUMSUB_WEBHOOK_SECRET: str = ""

    # ---- S3 / MinIO --------------------------------------------------------
    S3_ENDPOINT: Optional[str] = None
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_BUCKET: Optional[str] = None
    S3_REGION: str = "us-east-1"
    S3_SECURE: bool = False

    # ---- Anthropic ---------------------------------------------------------
    ANTHROPIC_API_KEY: Optional[str] = None
    # Modèle Claude Vision utilisé pour l'OCR (surchargeable sans redéploiement).
    ANTHROPIC_OCR_MODEL: str = "claude-sonnet-5"

    # ---- Observability -----------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_JSON: bool = True
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # ---- Rate limit --------------------------------------------------------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_LOGIN_PER_IP_DAY: str = "200/day"

    # ---- Redis / Cache -----------------------------------------------------
    REDIS_URL: Optional[str] = None  # ex: redis://localhost:6379/0
    MATCHING_CACHE_TTL_SECONDS: int = 300       # 5min
    MATCHING_CACHE_ENABLED: bool = True

    # ---- Celery (job queue) -----------------------------------------------
    # Si CELERY_BROKER_URL absent ET REDIS_URL absent → mode eager (sync inline).
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    CELERY_TASK_TIME_LIMIT_SECONDS: int = 300   # hard kill après 5min
    CELERY_TASK_SOFT_LIMIT_SECONDS: int = 240   # SIGTERM gracieux après 4min

    # ---- CORS --------------------------------------------------------------
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "https://app.simandou-screening.com",
            "https://backoffice.simandou-screening.com",
            "http://localhost:5173",
        ]
    )

    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_dev(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def effective_celery_broker(self) -> Optional[str]:
        """CELERY_BROKER_URL si défini, sinon REDIS_URL, sinon None (→ eager mode)."""
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def effective_celery_backend(self) -> Optional[str]:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    @property
    def celery_eager(self) -> bool:
        """True si pas de broker → Celery exécute les tâches inline (mode dégradé)."""
        return not self.effective_celery_broker

    @property
    def cache_enabled(self) -> bool:
        """True seulement si Redis configuré ET cache matching activé."""
        return bool(self.REDIS_URL) and self.MATCHING_CACHE_ENABLED

    # ------------------------------------------------------------------
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _enforce_secrets(self) -> "Settings":
        """
        Fail-fast en prod si secrets manquants ou faibles.
        En dev: warn et auto-génère une SECRET_KEY éphémère.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # SECRET_KEY
        if self.SECRET_KEY in _INSECURE_SECRETS or len(self.SECRET_KEY) < 32:
            if self.is_production:
                errors.append(
                    "SECRET_KEY missing or too weak (<32 chars / known default). "
                    "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
                )
            else:
                # Dev: génère une clé éphémère persistante pour la durée du process
                ephemeral = secrets.token_urlsafe(48)
                object.__setattr__(self, "SECRET_KEY", ephemeral)
                warnings.append(
                    "SECRET_KEY missing in dev — ephemeral key generated for this process. "
                    "Tokens will be invalid after restart. Set SECRET_KEY in .env to persist sessions."
                )

        # ADMIN_TOKEN
        if self.ADMIN_TOKEN in _INSECURE_SECRETS or len(self.ADMIN_TOKEN) < 24:
            if self.is_production:
                errors.append(
                    "ADMIN_TOKEN missing or too weak (<24 chars / known default). "
                    "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
                )
            else:
                ephemeral = "dev-" + secrets.token_urlsafe(24)
                object.__setattr__(self, "ADMIN_TOKEN", ephemeral)
                warnings.append(
                    "ADMIN_TOKEN missing in dev — ephemeral token generated. "
                    "Set ADMIN_TOKEN in .env to persist admin access."
                )

        # DATABASE_URL sanity
        if self.is_production:
            if "localhost" in self.DATABASE_URL or "127.0.0.1" in self.DATABASE_URL:
                warnings.append("DATABASE_URL points to localhost in production — is that intentional?")
            if ":postgres@" in self.DATABASE_URL or ":password@" in self.DATABASE_URL:
                errors.append("DATABASE_URL uses a default/example password — rotate before production boot.")

        # S3 obligatoire en prod (S3 sprint : on durcit)
        if self.is_production:
            if self.STORAGE_BACKEND == "LOCAL":
                errors.append(
                    "STORAGE_BACKEND=LOCAL is forbidden in production "
                    "(uploaded files would be lost on redeploy). "
                    "Set STORAGE_BACKEND=S3 and provide S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY/S3_BUCKET."
                )
            elif self.STORAGE_BACKEND == "S3":
                missing = [
                    n for n, v in (
                        ("S3_ENDPOINT", self.S3_ENDPOINT),
                        ("S3_ACCESS_KEY", self.S3_ACCESS_KEY),
                        ("S3_SECRET_KEY", self.S3_SECRET_KEY),
                        ("S3_BUCKET", self.S3_BUCKET),
                    ) if not v
                ]
                if missing:
                    errors.append(
                        f"STORAGE_BACKEND=S3 but missing required vars: {', '.join(missing)}"
                    )

        # Anthropic
        if not self.ANTHROPIC_API_KEY:
            warnings.append("ANTHROPIC_API_KEY missing — Claude Vision OCR will fail.")

        for w in warnings:
            logger.warning("[config] %s", w)

        if errors:
            for e in errors:
                logger.critical("[config] %s", e)
            sys.stderr.write(
                "\n\033[31m[FATAL] Refusing to boot: insecure configuration detected.\033[0m\n"
                + "\n".join(f"  - {e}" for e in errors)
                + "\n\n"
            )
            raise RuntimeError(
                "Insecure configuration — refusing to boot.\n  - "
                + "\n  - ".join(errors)
            )

        return self


settings = Settings()

# Backwards-compat aliases (le code existant en dépend)
ADMIN_TOKEN = settings.ADMIN_TOKEN
