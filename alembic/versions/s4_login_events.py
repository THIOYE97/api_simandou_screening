"""S4: journal des connexions (login_events) + dernière connexion sur users

Revision ID: s4_login_events
Revises: m13_offshore_relations
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "s4_login_events"
down_revision = "m13_offshore_relations"
branch_labels = None
depends_on = None

# Le rôle applicatif qui contourne RLS pour l'authentification (cf.
# settings.AUTH_BYPASS_ROLE). Les événements de connexion sont écrits SOUS ce
# rôle, puisque l'écriture a lieu pendant le login — avant qu'un contexte de
# tenant n'existe. Sans le GRANT ci-dessous, l'insertion échouerait en
# production alors qu'elle passe en test (où le rôle reçoit tous les droits).
AUTH_BYPASS_ROLE = "auth_bypass_rls"


def upgrade() -> None:
    op.create_table(
        "login_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32), nullable=True),
        # Pas de ForeignKey volontairement : la trace doit survivre à la
        # suppression du compte, et un échec sur une adresse inconnue n'a
        # aucun utilisateur à référencer.
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "is_new_context",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_login_events_created_at", "login_events", ["created_at"])
    op.create_index("ix_login_events_user_created", "login_events", ["user_id", "created_at"])
    op.create_index("ix_login_events_email", "login_events", ["email"])
    op.create_index("ix_login_events_ip", "login_events", ["ip"])

    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_ip", sa.String(64), nullable=True))

    # Droits pour le rôle d'authentification, s'il existe sur cette instance.
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{AUTH_BYPASS_ROLE}') THEN
            GRANT SELECT, INSERT ON public.login_events TO {AUTH_BYPASS_ROLE};
            GRANT SELECT, UPDATE ON public.users TO {AUTH_BYPASS_ROLE};
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_ip")
    op.drop_column("users", "last_login_at")
    op.drop_index("ix_login_events_ip", table_name="login_events")
    op.drop_index("ix_login_events_email", table_name="login_events")
    op.drop_index("ix_login_events_user_created", table_name="login_events")
    op.drop_index("ix_login_events_created_at", table_name="login_events")
    op.drop_table("login_events")
