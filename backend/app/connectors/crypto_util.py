"""Crypto address helpers: network detection and normalisation."""

from __future__ import annotations

import re

_PATTERNS = [
    ("BTC", re.compile(r"^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")),
    ("ETH", re.compile(r"^0x[a-fA-F0-9]{40}$")),
    ("TRON", re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")),
]

# OFAC "Digital Currency Address - <code>" codes -> network of the address
OFAC_CURRENCY_CHAIN = {
    "XBT": "BTC",
    "ETH": "ETH",
    "USDT": None,
    "USDC": "ETH",
    "TRX": "TRON",
    "LTC": "LTC",
    "BSC": "ETH",
    "ARB": "ETH",
    "XMR": "XMR",
    "BCH": "BCH",
    "ZEC": "ZEC",
    "DASH": "DASH",
    "BTG": "BTG",
    "ETC": "ETC",
    "XVG": "XVG",
    "SOL": "SOL",
}


def detect_chain(value: str) -> str | None:
    value = (value or "").strip()
    for chain, pattern in _PATTERNS:
        if pattern.match(value):
            return chain
    return None


def normalize_address(address: str, chain: str | None = None) -> str:
    """ETH addresses are case-insensitive (checksum casing): compare in lower case."""
    address = address.strip()
    chain = chain or detect_chain(address)
    return address.lower() if chain == "ETH" or address.startswith("0x") else address


def wallet_id(chain: str, address: str) -> str:
    return f"wallet:{chain.lower()}:{normalize_address(address, chain)}"


def short(address: str) -> str:
    return address if len(address) <= 14 else f"{address[:6]}…{address[-4:]}"
