# app/core/logging.py
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ContextVars pour enrichir les logs avec le contexte de requête.
# Définies ici (et pas dans un middleware) pour éviter les imports circulaires.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="-")


_SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "secret",
    "secret_key",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "anthropic_api_key",
    "database_url",
    "dsn",
}


def _redact(value: Any) -> Any:
    """Masquage best-effort des valeurs sensibles avant log."""
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _SENSITIVE_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(v) for v in value)
    return value


class JsonFormatter(logging.Formatter):
    """Formatter JSON minimaliste, sans dépendance externe."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
            "user_id": user_id_ctx.get(),
            "tenant_id": tenant_id_ctx.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        # Extra fields (logger.info("msg", extra={"foo": "bar"}))
        for key, value in record.__dict__.items():
            if key in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
                "taskName",
            ):
                continue
            payload[key] = _redact(value)

        try:
            return json.dumps(payload, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            payload["_serialize_error"] = True
            return json.dumps(
                {k: str(v) for k, v in payload.items()},
                ensure_ascii=False,
            )


class PlainFormatter(logging.Formatter):
    """Format lisible pour dev local."""

    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_ctx.get()
        base = super().format(record)
        return f"[{rid}] {base}"


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """À appeler une fois au démarrage. Idempotent."""
    root = logging.getLogger()
    # purge les handlers existants (Uvicorn en installe par défaut)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            PlainFormatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
        )

    root.addHandler(handler)
    root.setLevel(level)

    # Aligne les loggers Uvicorn / SQLAlchemy / FastAPI sur le même handler
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(noisy)
        lg.handlers = []
        lg.propagate = True

    # SQL queries: silencieux par défaut, activable via LOG_LEVEL=DEBUG
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if level == "DEBUG" else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
