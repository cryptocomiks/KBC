"""Build config/country_risk.json from three public country-risk indicators.

* Basel AML Index (Basel Institute on Governance) — money laundering and
  terrorist financing risk, 0 (low) to 10 (high). Public ranking page.
* Corruption Perceptions Index (Transparency International) — 0 (highly
  corrupt) to 100 (very clean). Via Our World in Data (CC BY).
* Worldwide Governance Indicators, Control of Corruption (World Bank) —
  about -2.5 (weak) to +2.5 (strong). World Bank API (CC BY 4.0).

Run by the "Country risk data" GitHub workflow (monthly), which commits the
result. Requires: pip install httpx pycountry
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path

import httpx
import pycountry

OUT = Path(__file__).resolve().parents[1] / "config" / "country_risk.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping; +https://github.com/cryptocomiks/KBC)"}
BASEL = "https://index.baselgovernance.org/ranking"
CPI = "https://ourworldindata.org/grapher/ti-corruption-perception-index.csv?v=1&csvType=full&useColumnShortNames=true"
WGI = "https://api.worldbank.org/v2/country/all/indicator/GOV_WGI_CC.EST"

# Names used by the sources that pycountry does not resolve on its own.
ALIASES = {
    "kosovo": "XK",
    "turkey": "TR",
    "türkiye": "TR",
    "turkiye": "TR",
    "russia": "RU",
    "iran": "IR",
    "syria": "SY",
    "laos": "LA",
    "lao pdr": "LA",
    "vietnam": "VN",
    "viet nam": "VN",
    "south korea": "KR",
    "korea, republic of": "KR",
    "korea, rep.": "KR",
    "north korea": "KP",
    "democratic republic of the congo": "CD",
    "congo, democratic republic": "CD",
    "congo, dem. rep.": "CD",
    "republic of the congo": "CG",
    "congo, rep.": "CG",
    "congo": "CG",
    "cote d'ivoire": "CI",
    "côte d'ivoire": "CI",
    "ivory coast": "CI",
    "cabo verde": "CV",
    "cape verde": "CV",
    "czech republic": "CZ",
    "czechia": "CZ",
    "eswatini": "SZ",
    "swaziland": "SZ",
    "moldova": "MD",
    "tanzania": "TZ",
    "bolivia": "BO",
    "venezuela": "VE",
    "micronesia": "FM",
    "palestine": "PS",
    "west bank and gaza": "PS",
    "hong kong": "HK",
    "hong kong sar, china": "HK",
    "macao": "MO",
    "macau": "MO",
    "taiwan": "TW",
    "brunei": "BN",
    "the bahamas": "BS",
    "bahamas": "BS",
    "the gambia": "GM",
    "gambia": "GM",
    "north macedonia": "MK",
    "st. kitts and nevis": "KN",
    "saint kitts and nevis": "KN",
    "st. lucia": "LC",
    "saint lucia": "LC",
    "st. vincent and the grenadines": "VC",
    "saint vincent and the grenadines": "VC",
    "timor-leste": "TL",
    "east timor": "TL",
    "united states": "US",
    "united kingdom": "GB",
    "curacao": "CW",
    "curaçao": "CW",
    "sao tome and principe": "ST",
    "são tomé and príncipe": "ST",
    "kyrgyzstan": "KG",
    "kyrgyz republic": "KG",
    "slovak republic": "SK",
    "yemen, rep.": "YE",
    "egypt, arab rep.": "EG",
    "iran, islamic rep.": "IR",
    "venezuela, rb": "VE",
    "gambia, the": "GM",
    "bahamas, the": "BS",
    "micronesia, fed. sts.": "FM",
    "virgin islands (u.s.)": "VI",
    "british virgin islands": "VG",
}


def iso2(name: str) -> str | None:
    key = re.sub(r"\s+", " ", name.strip().lower())
    if key in ALIASES:
        return ALIASES[key]
    for attempt in (name, name.split(",")[0], re.sub(r"\(.*?\)", "", name)):
        try:
            return pycountry.countries.lookup(attempt.strip()).alpha_2
        except LookupError:
            continue
    try:
        return pycountry.countries.search_fuzzy(name)[0].alpha_2
    except LookupError:
        return None


def basel(client: httpx.Client) -> dict[str, dict]:
    page = client.get(BASEL).text
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 3 or not re.fullmatch(r"\d+(\.\d+)?", cells[2]):
            continue
        code = iso2(cells[1])
        if code:
            out[code] = {"basel_aml_score": float(cells[2]), "basel_aml_rank": int(cells[0]), "name": cells[1]}
        else:
            print("basel: unmapped", cells[1])
    return out


def cpi(client: httpx.Client) -> dict[str, dict]:
    rows = list(csv.DictReader(io.StringIO(client.get(CPI).text)))
    latest: dict[str, dict] = {}
    for r in rows:
        code3 = r.get("code") or ""
        if len(code3) != 3 or not r.get("cpi_score"):
            continue
        c = pycountry.countries.get(alpha_3=code3)
        code = c.alpha_2 if c else ("XK" if code3 == "OWID_KOS" else None)
        if not code:
            continue
        year = int(r["year"])
        if code not in latest or year > latest[code]["cpi_year"]:
            latest[code] = {"cpi_score": float(r["cpi_score"]), "cpi_year": year}
    return latest


def wgi(client: httpx.Client) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for year in range(date.today().year - 1, date.today().year - 5, -1):
        data = client.get(WGI, params={"format": "json", "date": str(year), "per_page": 400, "source": 3}).json()
        if len(data) < 2 or not data[1]:
            continue
        for r in data[1]:
            if r.get("value") is None:
                continue
            code = None
            if r.get("countryiso3code"):
                c = pycountry.countries.get(alpha_3=r["countryiso3code"])
                code = c.alpha_2 if c else None
            code = code or iso2((r.get("country") or {}).get("value") or "")
            if code and code not in out:
                out[code] = {"wgi_control_of_corruption": round(float(r["value"]), 2), "wgi_year": year}
        if len(out) > 150:
            break
    return out


def main() -> None:
    with httpx.Client(headers=UA, timeout=60, follow_redirects=True) as client:
        b, c, w = basel(client), cpi(client), wgi(client)
    codes = sorted(set(b) | set(c) | set(w))
    countries = {}
    for code in codes:
        country = pycountry.countries.get(alpha_2=code)
        entry = {"name": country.name if country else b.get(code, {}).get("name", code)}
        for src in (b, c, w):
            entry.update({k: v for k, v in src.get(code, {}).items() if k != "name"})
        countries[code] = entry
    doc = {
        "retrieved": date.today().isoformat(),
        "sources": {
            "basel_aml": {"label": "Basel AML Index (public ranking)", "url": BASEL, "scale": "0 low – 10 high risk"},
            "cpi": {"label": "Corruption Perceptions Index (Transparency International, via Our World in Data)",
                    "url": "https://www.transparency.org/en/cpi", "scale": "0 highly corrupt – 100 very clean"},
            "wgi": {"label": "World Bank Worldwide Governance Indicators — Control of Corruption",
                    "url": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
                    "scale": "-2.5 weak – +2.5 strong"},
        },
        "countries": countries,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"basel={len(b)} cpi={len(c)} wgi={len(w)} countries={len(countries)} -> {OUT}")
    for code in ("CH", "LU", "FR", "GB", "US", "VG", "KY", "CY", "AE", "RU", "IR", "KP", "MM", "HT"):
        print(code, countries.get(code))


if __name__ == "__main__":
    main()
