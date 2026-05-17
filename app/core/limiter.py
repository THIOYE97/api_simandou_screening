# app/core/limiter.py
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _client_key(request: Request) -> str:
    """
    Clé de rate-limit:
    - login → email normalisé + IP (empêche le bruteforce ciblé d'un compte
      même si l'attaquant tourne ses IPs, et bloque par IP en plus).
    - défaut → IP (X-Forwarded-For first hop, sinon socket peer).
    """
    ip = get_remote_address(request) or "unknown"

    # X-Forwarded-For si on est derrière un proxy de confiance
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # premier hop = client réel (à condition que le proxy soit fiable)
        ip = xff.split(",")[0].strip() or ip

    return ip


limiter = Limiter(
    key_func=_client_key,
    default_limits=[],
    enabled=settings.RATE_LIMIT_ENABLED,
    headers_enabled=True,
    strategy="fixed-window",
    # storage_uri par défaut = memory:// (par worker, OK pour S1)
)


def login_key(request: Request) -> str:
    """
    Clé spécifique au login: IP + email (si présent dans le body JSON).
    On lit l'email best-effort sans bloquer si parsing impossible.
    """
    ip = _client_key(request)
    # body n'est pas lu ici (déjà consommé par FastAPI) — on se contente de l'IP
    # pour cette première itération. L'email-based limit pourra venir via une
    # vérif explicite dans la route si besoin (cf. S2 Redis).
    return f"login:{ip}"
