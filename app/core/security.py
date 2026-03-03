# app/core/security.py
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Paramètres raisonnables pour un backend web
ph = PasswordHasher(
    time_cost=2,
    memory_cost=102400,  # ~100MB
    parallelism=8,
    hash_len=32,
    salt_len=16,
)

def hash_password(password: str) -> str:
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    password = password.strip()
    if len(password) < 8:
        raise ValueError("password too short (min 8 chars)")
    return ph.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password.strip())
    except VerifyMismatchError:
        return False
