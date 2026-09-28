"""Quick checks on the details a client gives: IBAN, e-mail address / website, crypto address.

What a compliance officer checks by hand before accepting payment instructions or a
contact: is the IBAN valid, in which country and bank is the account, is that country
high-risk; is the e-mail domain a real, established mailbox (MX, SPF, DMARC, age) or a
free / disposable one, is the domain on a phishing list; is a wallet sanctioned or a
known scam address.

Nothing is stored: the details are checked and returned with the sources used.
Sources: SIX bank master (Swiss and Liechtenstein banks), DNS over HTTPS (Cloudflare,
Google), RDAP, the disposable-e-mail blocklist, MetaMask / ScamSniffer lists, OFAC / UN /
FBI / ransomware wallet lists (already used for screening).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date
from typing import Any

import httpx

from app.connectors.base import USER_AGENT, ConnectorError
from app.connectors.crypto_util import detect_chain, normalize_address, wallet_id
from app.connectors.free_sources import RDAP, YOUNG_DOMAIN_DAYS, _day, core_name
from app.matching.names import name_similarity
from app.models import Entity, EntityType
from app.risk.config import get_country_risk, get_jurisdictions

log = logging.getLogger(__name__)

TIMEOUT = 12.0
SIX_BANKMASTER = "https://api.six-group.com/api/epcd/bankmaster/v3/bankmaster.json"
DISPOSABLE = (
    "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/"
    "main/disposable_email_blocklist.conf"
)
DOH = ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve")

# ISO 13616 IBAN lengths
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22,
    "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "DO": 28,
    "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23,
    "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23, "IS": 26,
    "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20,
    "LV": 21, "LY": 25, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30,
    "NL": 18, "NO": 15, "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22,
    "RU": 33, "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "SO": 23,
    "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}  # fmt: skip
FREE_MAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "hotmail.fr", "live.com",
    "msn.com", "yahoo.com", "yahoo.fr", "ymail.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "gmx.com", "gmx.net", "gmx.ch", "gmx.de", "web.de", "proton.me",
    "protonmail.com", "pm.me", "tutanota.com", "tuta.io", "mail.com", "yandex.com",
    "yandex.ru", "mail.ru", "qq.com", "163.com", "orange.fr", "wanadoo.fr", "free.fr",
    "laposte.net", "sfr.fr", "bluewin.ch", "sunrise.ch", "hispeed.ch", "t-online.de",
    "libero.it", "zoho.com", "hey.com", "fastmail.com",
}  # fmt: skip
EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)$")

_CACHE: dict[str, tuple[float, Any]] = {}
_LOCK = threading.Lock()


def _cached(key: str, ttl: float, load) -> Any:
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = load()
    with _LOCK:
        _CACHE[key] = (time.time(), value)
    return value


def _get(url: str, **kw: Any) -> httpx.Response:
    return httpx.get(
        url,
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, **kw.pop("headers", {})},
        **kw,
    )


def _check(label: str, status: str, detail: str, source: str | None = None) -> dict[str, Any]:
    """status: ok | info | warn | alert | unknown"""
    return {"label": label, "status": status, "detail": detail, "source": source}


def _country(code: str) -> tuple[str, list[dict[str, Any]]]:
    jur = get_jurisdictions()
    name = jur.name(code)
    checks = []
    if code in jur.fatf_blacklist:
        checks.append(
            _check("Country", "alert", f"{name}: FATF call for action (black list)", "FATF")
        )
    elif code in jur.fatf_greylist:
        checks.append(
            _check("Country", "warn", f"{name}: FATF increased monitoring (grey list)", "FATF")
        )
    if code in jur.eu_tax_blacklist:
        checks.append(
            _check("Country", "warn", f"{name}: EU list of non-cooperative tax jurisdictions", "EU")
        )
    if code in jur.offshore_centres:
        checks.append(_check("Country", "info", f"{name}: offshore financial centre", "IMF list"))
    basel = get_country_risk().get(code).get("basel_aml_score")
    if basel:
        status = "warn" if float(basel) >= 6 else "info"
        checks.append(
            _check("Country", status, f"{name}: Basel AML Index {basel}/10", "Basel Institute")
        )
    if not checks:
        checks.append(_check("Country", "ok", f"{name}: not on the FATF / EU lists", "FATF, EU"))
    return name, checks


# ------------------------------------------------------------------------------ IBAN
def _six_banks() -> dict[int, dict[str, Any]]:
    def load() -> dict[int, dict[str, Any]]:
        resp = _get(SIX_BANKMASTER)
        resp.raise_for_status()
        out: dict[int, dict[str, Any]] = {}
        for e in resp.json().get("entries") or []:
            if isinstance(e.get("iid"), int):
                out.setdefault(e["iid"], e)
        return out

    return _cached("six", 24 * 3600, load)


def check_iban(raw: str, client_country: str | None = None) -> dict[str, Any]:
    iban = re.sub(r"\s+", "", raw or "").upper()
    out: dict[str, Any] = {"input": raw, "normalized": " ".join(re.findall(".{1,4}", iban))}
    checks: list[dict[str, Any]] = []
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", iban):
        checks.append(_check("Format", "alert", "Not an IBAN (2 letters, 2 check digits, account)"))
        return {**out, "valid": False, "checks": checks}
    cc = iban[:2]
    expected = IBAN_LENGTHS.get(cc)
    if expected and len(iban) != expected:
        checks.append(
            _check("Length", "alert", f"{len(iban)} characters, {expected} expected for {cc}")
        )
    digits = "".join(str(int(ch, 36)) for ch in iban[4:] + iban[:4])
    valid = int(digits) % 97 == 1 and (not expected or len(iban) == expected)
    checks.insert(
        0,
        _check(
            "Check digits",
            "ok" if int(digits) % 97 == 1 else "alert",
            "valid (ISO 13616 mod-97)"
            if int(digits) % 97 == 1
            else "invalid: typo or forged number",
            "ISO 13616",
        ),
    )
    if not expected:
        checks.append(_check("Country", "warn", f"{cc}: country without IBAN in the ISO registry"))
    country, cchecks = _country(cc)
    out["country"] = {"code": cc, "name": country}
    checks += cchecks
    if client_country and client_country.upper() != cc:
        checks.append(
            _check(
                "Account location",
                "info",
                f"account held in {country}, client based in {get_jurisdictions().name(client_country)}: "
                "ask why the account is abroad",
            )
        )
    if cc in ("CH", "LI") and valid:
        iid = int(iban[4:9])
        try:
            bank = _six_banks().get(iid)
        except (httpx.HTTPError, ValueError) as exc:
            log.info("SIX bank master unavailable: %s", exc)
            bank = None
            checks.append(_check("Bank", "unknown", "SIX bank master unreachable", "SIX"))
        else:
            if bank:
                out["bank"] = {
                    "name": bank.get("bankOrInstitutionName"),
                    "bic": bank.get("bic"),
                    "town": bank.get("townName"),
                    "iid": iid,
                }
                checks.append(
                    _check(
                        "Bank",
                        "ok",
                        f"{bank.get('bankOrInstitutionName')}, {bank.get('townName')}"
                        + (f": BIC {bank['bic']}" if bank.get("bic") else ""),
                        "SIX bank master",
                    )
                )
            else:
                checks.append(
                    _check(
                        "Bank", "alert", f"clearing number {iid} not in the SIX bank master", "SIX"
                    )
                )
    return {**out, "valid": valid, "checks": checks}


# ------------------------------------------------------------------------------ DNS
def _dns(name: str, rtype: str) -> list[str] | None:
    for url in DOH:
        try:
            resp = _get(
                url,
                params={"name": name, "type": rtype},
                headers={"accept": "application/dns-json"},
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            continue
        if data.get("Status") == 3:  # NXDOMAIN
            return []
        return [
            str(a.get("data", "")).strip('"')
            for a in data.get("Answer") or []
            if a.get("type") == {"MX": 15, "TXT": 16, "A": 1, "NS": 2}.get(rtype)
        ]
    return None


def _disposable() -> set[str]:
    def load() -> set[str]:
        resp = _get(DISPOSABLE)
        resp.raise_for_status()
        return {line.strip().lower() for line in resp.text.splitlines() if line.strip()}

    return _cached("disposable", 24 * 3600, load)


def _rdap_created(domain: str) -> tuple[date | None, str]:
    try:
        resp = _get(RDAP.format(domain=domain))
        data = resp.json() if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return None, ""
    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events") or []}
    registrar = ""
    for ent in data.get("entities") or []:
        if "registrar" in (ent.get("roles") or []):
            for field in ((ent.get("vcardArray") or [None, []])[1]) or []:
                if isinstance(field, list) and field and field[0] == "fn":
                    registrar = str(field[3])
    return _day(events.get("registration")), registrar


def check_domain(domain: str, *, mailbox: bool, company: str | None = None) -> list[dict[str, Any]]:
    from app.connectors.extra_sources import ScamListsConnector

    checks: list[dict[str, Any]] = []
    domain = domain.lower().strip().removeprefix("www.")
    if mailbox and domain in FREE_MAIL:
        checks.append(
            _check(
                "Mailbox",
                "warn" if company else "info",
                f"{domain} is a free consumer mailbox"
                + (": unusual for a company: ask for a corporate address" if company else ""),
            )
        )
    try:
        if domain in _disposable():
            checks.append(
                _check(
                    "Mailbox",
                    "alert",
                    "disposable / throw-away e-mail domain",
                    "disposable-email-domains",
                )
            )
    except httpx.HTTPError:
        pass
    free = domain in FREE_MAIL
    if not free:
        if mailbox:
            mx = _dns(domain, "MX")
            if mx is None:
                checks.append(_check("Mail server (MX)", "unknown", "DNS lookup failed", "DNS"))
            elif not mx:
                checks.append(
                    _check(
                        "Mail server (MX)",
                        "alert",
                        "no mail server: this address cannot receive e-mail",
                        "DNS",
                    )
                )
            else:
                checks.append(
                    _check(
                        "Mail server (MX)",
                        "ok",
                        ", ".join(m.split()[-1].rstrip(".") for m in mx[:2]),
                        "DNS",
                    )
                )
            txt = _dns(domain, "TXT") or []
            spf = next((t for t in txt if t.lower().startswith("v=spf1")), None)
            dmarc = next(
                (t for t in _dns(f"_dmarc.{domain}", "TXT") or [] if "v=dmarc1" in t.lower()), None
            )
            checks.append(
                _check(
                    "Anti-spoofing (SPF / DMARC)",
                    "ok" if spf and dmarc else "warn",
                    ("SPF " + ("present" if spf else "missing"))
                    + " · DMARC "
                    + (
                        re.search(r"p=(\w+)", dmarc).group(1)
                        if dmarc and re.search(r"p=(\w+)", dmarc)
                        else "missing"
                    )
                    + ("" if spf and dmarc else ": e-mails from this domain are easy to spoof"),
                    "DNS",
                )
            )
        created, registrar = _rdap_created(domain)
        if created:
            young = (date.today() - created).days < YOUNG_DOMAIN_DAYS
            checks.append(
                _check(
                    "Domain age",
                    "warn" if young else "ok",
                    f"registered {created.isoformat()}"
                    + (": less than a year old" if young else "")
                    + (f" · {registrar}" if registrar else ""),
                    "RDAP",
                )
            )
        else:
            checks.append(
                _check("Domain age", "unknown", "registration date not published", "RDAP")
            )
        if company:
            label = domain.split(".")[0]
            score = name_similarity(core_name(company), label, "company")[0]
            squashed = re.sub(r"[^a-z0-9]", "", core_name(company).lower())
            if score < 60 and label not in squashed and squashed[:6] not in label:
                checks.append(
                    _check(
                        "Name match",
                        "info",
                        f"the domain does not resemble “{company}”: check it is theirs",
                    )
                )
    try:
        listed = ScamListsConnector().domain_hits(domain)
    except ConnectorError:
        checks.append(_check("Scam lists", "unknown", "lists unavailable", "MetaMask, ScamSniffer"))
    else:
        checks.append(
            _check("Scam lists", "alert", f"listed: {listed}", listed)
            if listed
            else _check(
                "Scam lists",
                "ok",
                "not on the phishing / scam domain lists",
                "MetaMask, ScamSniffer",
            )
        )
    return checks


def check_email(raw: str, company: str | None = None) -> dict[str, Any]:
    email = (raw or "").strip()
    m = EMAIL.match(email)
    if not m:
        return {
            "input": raw,
            "valid": False,
            "checks": [_check("Format", "alert", "not a valid e-mail address")],
        }
    domain = m.group(1).lower()
    return {
        "input": raw,
        "valid": True,
        "domain": domain,
        "checks": check_domain(domain, mailbox=True, company=company),
    }


def check_website(raw: str, company: str | None = None) -> dict[str, Any]:
    host = re.sub(r"^[a-z]+://", "", (raw or "").strip().lower()).split("/")[0].split(":")[0]
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host):
        return {
            "input": raw,
            "valid": False,
            "checks": [_check("Format", "alert", "not a domain name")],
        }
    domain = host.removeprefix("www.")
    return {
        "input": raw,
        "valid": True,
        "domain": domain,
        "checks": check_domain(domain, mailbox=False, company=company),
    }


# ---------------------------------------------------------------------------- crypto
def check_wallet(raw: str) -> dict[str, Any]:
    from app.connectors.extra_sources import ScamListsConnector
    from app.connectors.official_sanctions import OfficialSanctionsConnector

    address = (raw or "").strip()
    chain = detect_chain(address)
    if not chain:
        return {
            "input": raw,
            "valid": False,
            "checks": [_check("Format", "alert", "not a BTC / ETH / TRON address")],
        }
    norm = normalize_address(address, chain)
    wallet = Entity(id=wallet_id(chain, norm), type=EntityType.WALLET, name=norm, chain=chain)
    checks = [
        _check(
            "Network",
            "info",
            {"BTC": "Bitcoin", "ETH": "Ethereum / EVM", "TRON": "TRON"}.get(chain, chain),
        )
    ]
    try:
        hits = OfficialSanctionsConnector().screen(wallet)
    except ConnectorError as exc:
        checks.append(_check("Sanctions", "unknown", str(exc)[:160], "OFAC, UN"))
    else:
        checks += (
            [
                _check("Sanctions", "alert", f"{h.dataset}: {h.matched_name}", h.dataset)
                for h in hits
            ]
            if hits
            else [
                _check(
                    "Sanctions",
                    "ok",
                    "not on OFAC, Israel NBCTF, FBI Lazarus or ransomware lists",
                    "OFAC, NBCTF, FBI, ransomwhe.re",
                )
            ]
        )
    if chain == "ETH":
        try:
            listed = ScamListsConnector().address_listed(norm)
        except ConnectorError:
            checks.append(_check("Scam lists", "unknown", "list unavailable", "ScamSniffer"))
        else:
            checks.append(
                _check("Scam lists", "alert", "known scam / drainer address", "ScamSniffer")
                if listed
                else _check("Scam lists", "ok", "not a known scam address", "ScamSniffer")
            )
    return {"input": raw, "valid": True, "chain": chain, "checks": checks}


def run_checks(payload: dict[str, Any]) -> dict[str, Any]:
    company = (payload.get("company") or "").strip() or None
    out: dict[str, Any] = {}
    if payload.get("iban"):
        out["iban"] = check_iban(payload["iban"], payload.get("client_country"))
    if payload.get("email"):
        out["email"] = check_email(payload["email"], company)
    if payload.get("website"):
        out["website"] = check_website(payload["website"], company)
    if payload.get("wallet"):
        out["wallet"] = check_wallet(payload["wallet"])
    order = {"alert": 0, "warn": 1, "unknown": 2, "info": 3, "ok": 4}
    worst = min(
        (order[c["status"]] for r in out.values() for c in r["checks"]),
        default=4,
    )
    out["verdict"] = ["alert", "warn", "unknown", "info", "ok"][worst]
    return out
