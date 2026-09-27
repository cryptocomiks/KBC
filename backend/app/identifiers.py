"""Recognise company identifiers typed in the search box.

Searching by identifier removes homonyms entirely: the analyst gets the exact
entity from the registry that issued the number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Identifier:
    kind: str  # siren | lei | ch_uid | uk_company | cik | br_cnpj | ru_ogrn | ru_inn | registration
    value: str  # normalised
    label: str  # shown to the analyst


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _cnpj_ok(d: str) -> bool:
    """Brazilian CNPJ check digits (modulo 11)."""
    if len(d) != 14 or len(set(d)) == 1:
        return False

    def digit(body: str, weights: list[int]) -> int:
        r = sum(int(a) * b for a, b in zip(body, weights, strict=True)) % 11
        return 0 if r < 2 else 11 - r

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return digit(d[:12], w1) == int(d[12]) and digit(d[:13], [6, *w1]) == int(d[13])


def _ogrn_ok(d: str) -> bool:
    """Russian OGRN (13 digits): the first 12 digits modulo 11, last digit of the rest."""
    return len(d) == 13 and int(d[:12]) % 11 % 10 == int(d[12])


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
    # Brazilian CNPJ (14 digits, often written 00.000.000/0000-00): also a valid SIRET length
    if (m := re.fullmatch(r"(?:CNPJ:?)?(\d{14})", compact)) and _cnpj_ok(m.group(1)):
        out.append(Identifier("br_cnpj", m.group(1), "Brazilian CNPJ"))
    # Russian OGRN (13 digits, check digit) and INN (with the "INN" prefix)
    if (m := re.fullmatch(r"(?:OGRN:?)?(\d{13})", compact)) and _ogrn_ok(m.group(1)):
        out.append(Identifier("ru_ogrn", m.group(1), "Russian OGRN"))
    if m := re.fullmatch(r"(?:INN|ИНН):?(\d{10}|\d{12})", compact):
        out.append(Identifier("ru_inn", m.group(1), "Russian INN"))
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
