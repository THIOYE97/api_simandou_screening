"""
Adapter ACP/ACH (télé-compense) — parsing d'un lot de compensation → transactions KYT.

Un fichier de compensation contient PLUSIEURS opérations (chèques / virements de
masse). Format supporté (PoC réaliste, délimité par « ; ») :

    REF;CUSTOMER;AMOUNT;CURRENCY;COUNTERPARTY;COUNTRY;TYPE
    CHQ001;C-1001;7500;GNF;Fournisseur X;GN;CHECK
    VIR002;C-2002;120000;USD;ACME Corp;US;TRANSFER

Lignes vides ou commençant par « # » ignorées ; en-tête optionnel ignoré.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models.kyt import Channel, Direction, SourceSystem

_HEADER_TOKENS = {"ref", "reference"}
_CHANNEL = {"CHECK": Channel.CHECK, "CHEQUE": Channel.CHECK, "TRANSFER": Channel.WIRE}


def _amount(v: str) -> Decimal:
    try:
        return Decimal(v.strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def parse_ach_batch(content: str) -> list[dict]:
    """Retourne une liste de dicts compatibles TransactionIn (une par opération)."""
    out: list[dict] = []
    for raw in (content or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if not parts or not parts[0]:
            continue
        if parts[0].lower() in _HEADER_TOKENS:  # ligne d'en-tête
            continue
        # remplissage défensif si colonnes manquantes
        parts += [""] * (7 - len(parts))
        ref, customer, amount, currency, counterparty, country, ttype = parts[:7]
        out.append({
            "external_ref": ref or None,
            "source_system": SourceSystem.ACH,
            "direction": Direction.OUT,
            "channel": _CHANNEL.get(ttype.upper(), Channel.WIRE),
            "amount": _amount(amount),
            "currency": (currency or "GNF").upper(),
            "customer_ref": customer or None,
            "counterparty_name": counterparty or None,
            "counterparty_country": (country or None) and country.upper(),
            "raw": {"source": "ACH", "line": line},
        })
    return out
