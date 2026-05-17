from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Réponse legacy — conservée pour compat. Préférer TokenPairResponse."""
    access_token: str
    token_type: str = "bearer"


class TokenPairResponse(BaseModel):
    """Nouveau format S3 : access + refresh."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # secondes avant expiration de l'access token
    refresh_expires_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None  # si fourni : révocation ciblée
    all_devices: bool = False            # si true : révoque toutes les sessions
