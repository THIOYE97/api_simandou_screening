"""
Adapter RTGS — mappe un message de règlement interbancaire temps réel
(structure inspirée d'ISO 20022 pacs.008) vers une transaction KYT.

Message attendu (JSON simplifié) :
    {
      "msgId": "RTGS-2026-0001",
      "debtor": {"ref": "C-1001"},
      "creditor": {"name": "Beta Bank", "country": "FR"},
      "amount": "500000", "currency": "USD",
      "direction": "OUT"
    }
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models.kyt import Channel, Direction, SourceSystem

_DIRECTION = {"IN": Direction.IN, "OUT": Direction.OUT, "INTERNAL": Direction.INTERNAL}


def map_rtgs_message(msg: dict) -> dict:
    """Retourne un dict compatible TransactionIn."""
    debtor = msg.get("debtor") or {}
    creditor = msg.get("creditor") or {}
    try:
        amount = Decimal(str(msg.get("amount", 0)))
    except InvalidOperation:
        amount = Decimal("0")

    return {
        "external_ref": msg.get("msgId") or msg.get("external_ref"),
        "source_system": SourceSystem.RTGS,
        "direction": _DIRECTION.get(str(msg.get("direction", "OUT")).upper(), Direction.OUT),
        "channel": Channel.WIRE,
        "amount": amount,
        "currency": (msg.get("currency") or "USD").upper(),
        "customer_ref": debtor.get("ref") or msg.get("customer_ref"),
        "counterparty_name": creditor.get("name"),
        "counterparty_country": (creditor.get("country") or None) and str(creditor["country"]).upper(),
        "raw": {"source": "RTGS", "message": msg},
    }
