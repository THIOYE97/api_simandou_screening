# app/models/login_event.py
"""
Journal des connexions (Module 2 — Contrôle Accès et Sécurité).

Le TDR exige des traces historisées systématiquement. Les tentatives d'accès
n'étaient jusqu'ici écrites que dans le journal applicatif (stdout de
l'hébergeur) : ni requêtables, ni conservées. On ne pouvait donc pas répondre
à « qui s'est connecté, depuis où, et quand » — qui est précisément la
question que se pose la Conformité après une remise d'offre ou un incident.

Deux choix de conception à connaître :

1. Les ÉCHECS sont journalisés au même titre que les succès. Une série
   d'échecs sur une adresse valide est le premier signe d'une attaque par
   force brute ; ne garder que les succès revient à ne voir que les attaques
   qui ont réussi.

2. Aucune clé étrangère vers `users`. Un événement doit survivre à la
   suppression du compte — sinon la piste d'audit s'efface en même temps que
   le compte suspect, ce qui la rend sans valeur probante. Et un échec sur une
   adresse inconnue n'a, par définition, aucun utilisateur à référencer :
   c'est `email` qui porte alors l'information.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class LoginEvent(Base):
    __tablename__ = "login_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # LOGIN_OK | LOGIN_FAILED | LOGOUT | REFRESH
    event = Column(String(16), nullable=False)
    # Motif d'échec ou précision : unknown_user | bad_password | disabled | rotated | logout_all
    reason = Column(String(32), nullable=True)

    # NULL si l'adresse saisie ne correspond à aucun compte.
    user_id = Column(UUID(as_uuid=True), nullable=True)
    # Toujours renseigné : c'est la saisie de l'utilisateur, y compris quand
    # elle ne correspond à rien.
    email = Column(Text, nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)

    ip = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Vrai quand cette connexion vient d'une adresse IP ou d'un appareil
    # jamais observés pour ce compte. C'est ce drapeau qui déclenche l'alerte
    # par courriel — et qui permet de retrouver les connexions notables sans
    # relire tout le journal.
    is_new_context = Column(Boolean, nullable=False, server_default=text("false"))

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_login_events_created_at", "created_at"),
        Index("ix_login_events_user_created", "user_id", "created_at"),
        Index("ix_login_events_email", "email"),
        Index("ix_login_events_ip", "ip"),
    )
