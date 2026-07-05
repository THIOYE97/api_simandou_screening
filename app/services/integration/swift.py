"""
Adapter SWIFT — parsing d'un message MT103 (virement client) → transaction KYT.

PoC : extrait les champs essentiels (référence, montant/devise/date de valeur,
donneur d'ordre, bénéficiaire). Un connecteur production gérerait MT/MX (ISO 20022)
complets et le rapprochement des champs 50/59 avec le référentiel client.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.models.kyt import Channel, Direction, SourceSystem

_TAG_RE = re.compile(r":(\d{2}[A-Z]?):", re.M)


def _split_tags(message: str) -> dict[str, str]:
    """Découpe un message SWIFT en {tag: valeur}."""
    tags: dict[str, str] = {}
    matches = list(_TAG_RE.finditer(message))
    for i, m in enumerate(matches):
        tag = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(message)
        tags[tag] = message[start:end].strip()
    return tags


def _parse_32a(value: str) -> tuple[datetime | None, str, Decimal]:
    """
    :32A: = date valeur (YYMMDD) + devise (3) + montant (décimale virgule).
    Ex : '250701USD15000,00'
    """
    m = re.match(r"(\d{6})([A-Z]{3})([\d.,]+)", value.strip())
    if not m:
        return None, "USD", Decimal("0")
    raw_date, currency, raw_amount = m.groups()
    try:
        value_date = datetime.strptime(raw_date, "%y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        value_date = None
    amount_str = raw_amount.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        amount = Decimal("0")
    return value_date, currency, amount


def parse_mt103(message: str) -> dict:
    """Retourne un dict compatible TransactionIn."""
    tags = _split_tags(message)
    value_date, currency, amount = _parse_32a(tags.get("32A", ""))

    ordering = tags.get("50K") or tags.get("50A") or tags.get("50F") or ""
    beneficiary = tags.get("59") or tags.get("59A") or ""

    # heuristique pays bénéficiaire : dernier token à 2 lettres majuscules
    country = None
    m = re.search(r"\b([A-Z]{2})\b", beneficiary.splitlines()[-1] if beneficiary else "")
    if m:
        country = m.group(1)

    return {
        "external_ref": tags.get("20"),
        "source_system": SourceSystem.SWIFT,
        "direction": Direction.OUT,
        "channel": Channel.WIRE,
        "amount": amount,
        "currency": currency,
        "customer_ref": ordering.splitlines()[0].strip() if ordering else None,
        "counterparty_name": beneficiary.splitlines()[0].strip() if beneficiary else None,
        "counterparty_country": country,
        "value_date": value_date,
        "raw": {"tags": tags, "message_type": "MT103"},
    }
