import hashlib
from datetime import datetime, timezone
from sqlalchemy import text
from fastapi import HTTPException
import bcrypt


def accept_invitation(db, raw_token: str, password: str):
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    invite = db.execute(
        text("""
          SELECT *
          FROM tenant_invitations
          WHERE token_hash = :h
            AND accepted_at IS NULL
            AND expires_at > now()
        """),
        {"h": token_hash},
    ).mappings().first()

    if not invite:
        raise ValueError("Invitation invalid or expired")

    email = invite["email"]
    tenant_id = invite["tenant_id"]
    role = invite["role"]

    # check user exists
    user = db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": email},
    ).scalar()

    if not user:
        pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        user_id = db.execute(
            text("""
              INSERT INTO users (id, email, password_hash, tenant_id, status, is_active)
              VALUES (gen_random_uuid(), :email, :ph, :tid, 'ACTIVE', true)
              RETURNING id
            """),
            {"email": email, "ph": pwd_hash, "tid": tenant_id},
        ).scalar()
    else:
        user_id = user

    # assign role
    db.execute(
        text("""
          INSERT INTO user_roles (tenant_id, user_id, role)
          VALUES (:tid, :uid, :role)
          ON CONFLICT DO NOTHING
        """),
        {"tid": tenant_id, "uid": user_id, "role": role},
    )

    # mark invitation accepted
    db.execute(
        text("""
          UPDATE tenant_invitations
          SET accepted_at = now()
          WHERE id = :iid
        """),
        {"iid": invite["id"]},
    )

    db.commit()

    return {"ok": True, "user_id": str(user_id), "tenant_id": str(tenant_id)}
