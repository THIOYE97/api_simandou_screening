"""
Adapter Temenos T24 — mappe une transaction du Core Banking (structure JSON /
IRIS) vers une transaction KYT normalisée.

PoC : mapping des champs usuels d'un enregistrement FUNDS.TRANSFER / TELLER.
Un connecteur production s'appuierait sur l'API Temenos (TAFJ/IRIS) et le
contrôle des seuils par type d'opération.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.kyt import Channel, Direction, SourceSystem

# Correspondance des instruments T24 → canal KYT
_CHANNEL_MAP = {
    "CASH": Channel.CASH,
    "TELLER": Channel.CASH,
    "CHEQUE": Channel.CHECK,
    "CHECK": Channel.CHECK,
    "TRANSFER": Channel.WIRE,
    "AC": Channel.WIRE,
}

_DIRECTION_MAP = {
    "DEBIT": Direction.OUT,
    "CREDIT": Direction.IN,
    "IN": Direction.IN,
    "OUT": Direction.OUT,
}


def map_t24_transaction(record: dict) -> dict:
    """Retourne un dict compatible TransactionIn à partir d'un enregistrement T24."""
    instrument = str(record.get("TRANSACTION.TYPE") or record.get("instrument") or "TRANSFER").upper()
    direction = str(record.get("DR.CR") or record.get("direction") or "DEBIT").upper()

    amount = record.get("AMOUNT") or record.get("amount") or 0
    try:
        amount = Decimal(str(amount))
    except Exception:
        amount = Decimal("0")

    return {
        "external_ref": record.get("@id") or record.get("TRANSACTION.REF") or record.get("external_ref"),
        "source_system": SourceSystem.T24,
        "direction": _DIRECTION_MAP.get(direction, Direction.OUT),
        "channel": _CHANNEL_MAP.get(instrument, Channel.WIRE),
        "amount": amount,
        "currency": record.get("CURRENCY") or record.get("currency") or "USD",
        "customer_ref": record.get("CUSTOMER.NO") or record.get("customer_ref"),
        "counterparty_name": record.get("BENEFICIARY.NAME") or record.get("counterparty_name"),
        "counterparty_country": record.get("BENEFICIARY.COUNTRY") or record.get("counterparty_country"),
        "raw": {"source": "T24", "record": record},
    }
