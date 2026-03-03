# app/api/routes/auth_invite.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_rls as get_db
from app.services.tenant_invites_service import accept_invitation

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/accept-invitation")
def accept_invite(payload: dict, db: Session = Depends(get_db)):
    token = payload.get("token")
    password = payload.get("password")

    if not token or not password:
        raise HTTPException(422, "token + password required")

    return accept_invitation(db, token, password)
