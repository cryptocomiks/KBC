"""Small parsing helpers shared by the real connectors."""

from __future__ import annotations

import re
from datetime import date

from unidecode import unidecode

# Demonyms / country names (EN + FR) -> ISO 3166-1 alpha-2. Extend as needed.
_NATIONALITIES = {
    "francaise": "FR",
    "francais": "FR",
    "french": "FR",
    "france": "FR",
    "britannique": "GB",
    "british": "GB",
    "english": "GB",
    "scottish": "GB",
    "welsh": "GB",
    "united kingdom": "GB",
    "uk": "GB",
    "anglaise": "GB",
    "americaine": "US",
    "american": "US",
    "united states": "US",
    "usa": "US",
    "allemande": "DE",
    "german": "DE",
    "germany": "DE",
    "italienne": "IT",
    "italian": "IT",
    "italy": "IT",
    "espagnole": "ES",
    "spanish": "ES",
    "spain": "ES",
    "portugaise": "PT",
    "portuguese": "PT",
    "belge": "BE",
    "belgian": "BE",
    "belgium": "BE",
    "suisse": "CH",
    "swiss": "CH",
    "switzerland": "CH",
    "luxembourgeoise": "LU",
    "luxembourger": "LU",
    "luxembourgish": "LU",
    "luxembourg": "LU",
    "neerlandaise": "NL",
    "dutch": "NL",
    "netherlands": "NL",
    "irlandaise": "IE",
    "irish": "IE",
    "ireland": "IE",
    "russe": "RU",
    "russian": "RU",
    "russia": "RU",
    "ukrainienne": "UA",
    "ukrainian": "UA",
    "chinoise": "CN",
    "chinese": "CN",
    "china": "CN",
    "marocaine": "MA",
    "moroccan": "MA",
    "morocco": "MA",
    "algerienne": "DZ",
    "algerian": "DZ",
    "tunisienne": "TN",
    "tunisian": "TN",
    "libanaise": "LB",
    "lebanese": "LB",
    "chypriote": "CY",
    "cypriot": "CY",
    "cyprus": "CY",
    "maltaise": "MT",
    "maltese": "MT",
    "grecque": "GR",
    "greek": "GR",
    "turque": "TR",
    "turkish": "TR",
    "israelienne": "IL",
    "israeli": "IL",
    "emirienne": "AE",
    "emirati": "AE",
    "united arab emirates": "AE",
    "saoudienne": "SA",
    "saudi": "SA",
    "saudi arabian": "SA",
    "qatarienne": "QA",
    "qatari": "QA",
    "indienne": "IN",
    "indian": "IN",
    "pakistanaise": "PK",
    "pakistani": "PK",
    "japonaise": "JP",
    "japanese": "JP",
    "canadienne": "CA",
    "canadian": "CA",
    "bresilienne": "BR",
    "brazilian": "BR",
    "australienne": "AU",
    "australian": "AU",
    "polonaise": "PL",
    "polish": "PL",
    "roumaine": "RO",
    "romanian": "RO",
    "bulgare": "BG",
    "bulgarian": "BG",
    "serbe": "RS",
    "serbian": "RS",
    "monegasque": "MC",
    "monaco": "MC",
    "senegalaise": "SN",
    "senegalese": "SN",
    "ivoirienne": "CI",
    "ivorian": "CI",
    "nigeriane": "NG",
    "nigerian": "NG",
    "sud-africaine": "ZA",
    "south african": "ZA",
    "somalienne": "SO",
    "somali": "SO",
}


def nationality_iso(value: str | None) -> list[str]:
    """'Française' / 'British' / 'FR' -> ['FR']; unknown values are dropped."""
    if not value:
        return []
    out = []
    for part in re.split(r"[,/;]| and | et ", value):
        key = unidecode(part).strip().lower()
        if not key:
            continue
        if len(key) == 2 and key.isalpha():
            out.append(key.upper())
        elif key in _NATIONALITIES:
            out.append(_NATIONALITIES[key])
    return sorted(set(out))


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def flexible_date(value: str | None) -> str | None:
    """'1966-05-02', '1966-05', '05/1966', '02/05/1966' -> ISO (possibly partial)."""
    if not value:
        return None
    value = value.strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.fullmatch(r"(\d{2})/(\d{4})", value)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    m = re.fullmatch(r"\d{4}(-\d{2}){0,2}", value)
    return value if m else None


def partial_date(year: object = None, month: object = None, day: object = None) -> str | None:
    """Build 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD' from optional parts."""
    if not year:
        return None
    out = f"{int(year):04d}"
    if month:
        out += f"-{int(month):02d}"
        if day:
            out += f"-{int(day):02d}"
    return out


def person_name(first: str | None, last: str | None) -> str:
    """'JEAN PIERRE', 'MARTIN' -> 'Jean Pierre MARTIN' → rendered as 'Jean Pierre Martin'."""
    parts = [p.strip() for p in (first or "", last or "") if p and p.strip()]
    return " ".join(w.capitalize() if w.isupper() else w for w in " ".join(parts).split())


def reorder_surname_first(name: str) -> str:
    """Companies House style 'SMITH, John Paul' -> 'John Paul Smith'."""
    if "," in name:
        last, first = name.split(",", 1)
        return person_name(first, last)
    return person_name(name, None)


def title_company(name: str) -> str:
    """Keep company names as published, only fixing all-caps names for display."""
    return name.strip()
