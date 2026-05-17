# app/core/cache.py
"""
Cache Redis avec fallback no-op.

- Si REDIS_URL est défini → vrai client Redis.
- Sinon → no-op (get retourne None, set ne fait rien).

Permet d'écrire le code applicatif sans `if redis_available:` partout.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("simandou.cache")


class _NoopCache:
    """Cache no-op. Méthodes async-friendly (sync ici, FastAPI gère)."""

    enabled = False

    def get(self, key: str) -> Optional[Any]:
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        return None

    def delete(self, key: str) -> None:
        return None

    def delete_pattern(self, pattern: str) -> int:
        return 0

    def health(self) -> dict:
        return {"backend": "noop", "ok": True}


class _RedisCache:
    """Wrapper minimaliste autour de redis-py."""

    enabled = True

    def __init__(self, url: str):
        # Import paresseux : pas de dep si REDIS_URL absent
        import redis  # type: ignore

        self._client = redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        self._url = url

    def get(self, key: str) -> Optional[Any]:
        try:
            raw = self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.exception("cache_get_failed", extra={"key": key})
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        try:
            payload = json.dumps(value, default=str).encode("utf-8")
            if ttl:
                self._client.setex(key, ttl, payload)
            else:
                self._client.set(key, payload)
        except Exception:
            logger.exception("cache_set_failed", extra={"key": key})

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception:
            logger.exception("cache_delete_failed", extra={"key": key})

    def delete_pattern(self, pattern: str) -> int:
        """Invalidation par préfixe. Utilise SCAN (sans bloquer Redis)."""
        try:
            n = 0
            for k in self._client.scan_iter(match=pattern, count=200):
                self._client.delete(k)
                n += 1
            return n
        except Exception:
            logger.exception("cache_delete_pattern_failed", extra={"pattern": pattern})
            return 0

    def health(self) -> dict:
        try:
            pong = self._client.ping()
            return {"backend": "redis", "ok": bool(pong)}
        except Exception as e:
            return {"backend": "redis", "ok": False, "error": str(e)}


def _build_cache():
    if not settings.REDIS_URL:
        logger.info("cache_disabled", extra={"reason": "no REDIS_URL"})
        return _NoopCache()
    try:
        c = _RedisCache(settings.REDIS_URL)
        logger.info("cache_enabled", extra={"backend": "redis"})
        return c
    except ImportError:
        logger.warning("cache_disabled", extra={"reason": "redis package missing"})
        return _NoopCache()
    except Exception:
        logger.exception("cache_init_failed_falling_back_to_noop")
        return _NoopCache()


cache = _build_cache()


# --- Helpers ----------------------------------------------------------------

def make_key(prefix: str, *parts: Any) -> str:
    """Génère une clé stable, hash si trop longue."""
    raw = ":".join(str(p) for p in parts)
    if len(raw) > 120:
        raw = hashlib.sha256(raw.encode()).hexdigest()
    return f"{prefix}:{raw}"
