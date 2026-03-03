# app/services/auth_service.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Dict
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

# ---------------------------------------------------------------------
# JWT settings (si tu les as déjà dans app/core/config.py, importe-les)
# ---------------------------------------------------------------------
# Exemple fallback: remplace par tes settings réels si existants
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24h

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
