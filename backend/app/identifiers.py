"""Recognise company identifiers typed in the search box.

Searching by identifier removes homonyms entirely: the analyst gets the exact
entity from the registry that issued the number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Identifier:
    kind: str  # siren | lei | ch_uid | uk_company | cik | registration
    value: str  # normalised
    label: str  # shown to the analyst


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def detect(query: str) -> list[Identifier]:
    q = query.strip().upper()
    compact = re.sub(r"[\s.\-/]", "", q)
    out: list[Identifier] = []
    # Swiss UID: CHE-123.456.789
    if re.fullmatch(r"CHE\d{9}", compact):
        d = compact[3:]
        out.append(Identifier("ch_uid", f"CHE-{d[:3]}.{d[3:6]}.{d[6:]}", "Swiss UID"))
    # French VAT FRxx + SIREN, SIRET (14 digits), SIREN (9 digits)
    elif m := re.fullmatch(r"FR[0-9A-Z]{2}(\d{9})", compact):
        out.append(Identifier("siren", m.group(1), "SIREN (from the French VAT number)"))
    elif re.fullmatch(r"\d{14}", compact):
        out.append(Identifier("siren", compact[:9], "SIREN (from the SIRET)"))
    elif re.fullmatch(r"\d{9}", compact):
        out.append(Identifier("siren", compact, "SIREN"))
    # LEI (ISO 17442): 18 alphanumerics + 2 check digits
    if re.fullmatch(r"[A-Z0-9]{18}\d{2}", compact) and not compact.isdigit():
        out.append(Identifier("lei", compact, "LEI"))
    # SEC Central Index Key
    if m := re.fullmatch(r"CIK0*(\d{1,10})", compact):
        out.append(Identifier("cik", m.group(1), "SEC CIK"))
    # UK Companies House number: 8 digits or 2 letters + 6 digits
    if re.fullmatch(r"\d{8}|(SC|NI|OC|SO|NC|R0|FC|GE|LP|SL|NL|IP|SP|RC|NP|NO)\d{6}", compact):
        out.append(Identifier("uk_company", compact, "UK company number"))
    # Generic register number (e.g. Luxembourg RCS B123456): exact match on registration numbers
    if not out and re.fullmatch(r"[A-Z]{0,3}\d{4,12}", compact):
        out.append(Identifier("registration", compact, "registration number"))
    return out
