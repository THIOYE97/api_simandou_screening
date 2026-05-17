# app/services/auth_service.py
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import jwt, JWTError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

# ---------------------------------------------------------------------
# JWT settings — viennent de app/core/config (S3 : access courts + refresh)
# ---------------------------------------------------------------------
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

# ---------------------------------------------------------------------
# Password hashing: Argon2 (default) + compat bcrypt
# ---------------------------------------------------------------------
_argon2 = PasswordHasher(
    time_cost=2,
    memory_cost=102400,  # ~100MB
    parallelism=8,
    hash_len=32,
    salt_len=16,
)

def hash_password(password: str, *, algo: str = "argon2") -> str:
    password = (password or "").strip()
    if len(password) < 8:
        raise ValueError("password too short (min 8 chars)")

    if algo == "bcrypt":
        pw_bytes = password.encode("utf-8")
        if len(pw_bytes) > 72:
            raise ValueError("bcrypt passwords must be <=72 bytes (use argon2)")
        return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")

    return _argon2.hash(password)

def verify_password(plain_password: str, password_hash: str) -> bool:
    plain_password = (plain_password or "").strip()
    password_hash = (password_hash or "").strip()
    if not plain_password or not password_hash:
        return False

    # Argon2
    if password_hash.startswith("$argon2"):
        try:
            return _argon2.verify(password_hash, plain_password)
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    # bcrypt
    if password_hash.startswith("$2a$") or password_hash.startswith("$2b$") or password_hash.startswith("$2y$"):
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
        except Exception:
            return False

    return False

def needs_rehash(password_hash: str) -> bool:
    ph = (password_hash or "").strip()
    return ph.startswith("$2a$") or ph.startswith("$2b$") or ph.startswith("$2y$")

# ---------------------------------------------------------------------
# JWT helpers (conserve decode_access_token attendu par deps/auth.py)
# ---------------------------------------------------------------------
def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dict(data)
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + expires_delta
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise ValueError("Invalid token") from e


def get_user_by_email(db: Session, email: str):
    email_norm = (email or "").strip().lower()

    row = db.execute(
        text("""
            SELECT
              id::text AS id,
              email,
              full_name,
              password_hash,
              is_active,
              status,
              tenant_id::text AS tenant_id
            FROM public.users
            WHERE lower(trim(email)) = :email
            LIMIT 1
        """),
        {"email": email_norm},
    ).mappings().first()

    if not row:
        return None


    return dict(row) if row else None


# ---------------------------------------------------------------------
# Refresh tokens (S3)
# ---------------------------------------------------------------------

# Longueur du token clair côté client. 48 octets urlsafe ~= 64 caractères.
_REFRESH_TOKEN_BYTES = 48


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex (64 chars). Pas de salt : on cherche par lookup exact."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(
    db: Session,
    *,
    user_id: str,
    tenant_id: str,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[str, datetime]:
    """
    Génère un refresh token clair (renvoyé une seule fois au client),
    persiste son SHA-256 + métadonnées. Retourne (token_clair, expires_at).
    """
    token = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
    token_hash = hash_refresh_token(token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    db.execute(
        text("""
            INSERT INTO refresh_tokens
                (user_id, tenant_id, token_hash, issued_at, expires_at, client_ip, user_agent)
            VALUES
                (CAST(:uid AS uuid), CAST(:tid AS uuid), :th, :iat, :exp, :ip, :ua)
        """),
        {
            "uid": user_id, "tid": tenant_id, "th": token_hash,
            "iat": now, "exp": expires_at,
            "ip": (client_ip or "")[:64] or None,
            "ua": (user_agent or "")[:512] or None,
        },
    )
    return token, expires_at


def consume_refresh_token(
    db: Session,
    *,
    token: str,
) -> Optional[Dict[str, Any]]:
    """
    Vérifie le refresh token côté DB. Retourne {user_id, tenant_id} ou None.
    NE COMMIT PAS — le caller décide si on rotate/revoke.
    """
    token_hash = hash_refresh_token(token)
    now = datetime.now(timezone.utc)
    row = db.execute(
        text("""
            SELECT
                id::text AS id,
                user_id::text AS user_id,
                tenant_id::text AS tenant_id,
                revoked_at,
                expires_at
            FROM refresh_tokens
            WHERE token_hash = :th
            LIMIT 1
        """),
        {"th": token_hash},
    ).mappings().first()

    if not row:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] < now:
        return None

    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "tenant_id": row["tenant_id"],
    }


def revoke_refresh_token(db: Session, *, token: str, reason: str = "logout") -> bool:
    """Révoque un refresh token (lookup par hash). True si trouvé/marqué."""
    token_hash = hash_refresh_token(token)
    res = db.execute(
        text("""
            UPDATE refresh_tokens
            SET revoked_at = now(), revoked_reason = :r
            WHERE token_hash = :th AND revoked_at IS NULL
        """),
        {"th": token_hash, "r": reason},
    )
    return (res.rowcount or 0) > 0


def revoke_all_user_tokens(db: Session, *, user_id: str, reason: str = "user_disabled") -> int:
    """Tue toutes les sessions actives d'un utilisateur. Retourne le nb révoqués."""
    res = db.execute(
        text("""
            UPDATE refresh_tokens
            SET revoked_at = now(), revoked_reason = :r
            WHERE user_id = CAST(:uid AS uuid) AND revoked_at IS NULL
        """),
        {"uid": user_id, "r": reason},
    )
    return int(res.rowcount or 0)


def purge_expired_refresh_tokens(db: Session) -> int:
    """À appeler depuis un cron. Supprime les refresh tokens expirés depuis >30j."""
    res = db.execute(
        text("""
            DELETE FROM refresh_tokens
            WHERE expires_at < now() - interval '30 days'
        """)
    )
    return int(res.rowcount or 0)
