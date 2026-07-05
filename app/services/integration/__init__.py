"""
Passerelle d'interfaçage (integration-gw) — Module d'interfaçage exogène (TDR §VI).

Chaque adapter convertit un format source (T24, SWIFT, ACP/ACH, RTGS) en une
transaction normalisée exploitable par le KYT (M5). Découplage total : le cœur
ne connaît que le format normalisé.
"""
from app.services.integration.ach import parse_ach_batch
from app.services.integration.rtgs import map_rtgs_message
from app.services.integration.swift import parse_mt103
from app.services.integration.t24 import map_t24_transaction

ADAPTERS = {
    "SWIFT": {"format": "MT103", "status": "available", "parser": parse_mt103},
    "T24": {"format": "JSON", "status": "available", "parser": map_t24_transaction},
    "ACH": {"format": "lot de compensation (délimité)", "status": "available", "parser": parse_ach_batch},
    "RTGS": {"format": "message ISO 20022 (pacs.008)", "status": "available", "parser": map_rtgs_message},
}

__all__ = ["parse_mt103", "map_t24_transaction", "parse_ach_batch", "map_rtgs_message", "ADAPTERS"]
