"""Linked websites — domains and sites run by the same operator as a company's website.

Public services, no key; runs in the website pass (after official websites
are known), like the Wayback Machine connector. Companies only.

1. Certificate transparency (crt.sh): domains listed on the same TLS
   certificates as the company's domain ("sister domains").
2. Shared analytics / tag-manager IDs (HackerTarget): other sites carrying the
   same Google Analytics / GTM identifier — the OCCRP "shared analytics code"
   method to find sites operated by the same people.

Results are leads (shared hosting providers or agencies can explain a link).
Network errors never fail the investigation: what was found is returned.
"""

from __future__ import annotations

import logging
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.wayback import websites
from app.models import Document, Entity, EntityType

log = logging.getLogger(__name__)

CRTSH = "https://crt.sh/"
CRTSH_PAGE = "https://crt.sh/?q=%25.{domain}"
ANALYTICS = "https://api.hackertarget.com/analyticslookup/"
MAX_DOMAINS_LISTED = 15
MAX_IDS = 3
MAX_HOSTS_LISTED = 15
#: second-level labels under which registrations happen (co.uk, com.au...): keep 3 labels
PUBLIC_SECOND_LEVELS = {
    "co.uk",
    "org.uk",
    "ac.uk",
    "gov.uk",
    "ltd.uk",
    "plc.uk",
    "me.uk",
    "com.au",
    "net.au",
    "org.au",
    "co.jp",
    "ne.jp",
    "or.jp",
    "com.br",
    "net.br",
    "co.nz",
    "co.za",
    "com.cn",
    "com.hk",
    "co.in",
    "com.sg",
    "com.mx",
    "co.kr",
    "com.tr",
    "com.ar",
    "co.il",
    "com.my",
    "co.id",
    "com.ua",
    "com.cy",
}


def registrable_domain(host: str) -> str | None:
    """ "*.shop.example.co.uk" -> "example.co.uk"; "a.b.example.com" -> "example.com"."""
    host = (host or "").strip().lower().rstrip(".")
    while host.startswith("*."):
        host = host[2:]
    if not host or "." not in host or " " in host or "@" in host:
        return None
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return None
    if len(labels) >= 3 and ".".join(labels[-2:]) in PUBLIC_SECOND_LEVELS:
        return ".".join(labels[-3:])
    if ".".join(labels[-2:]) in PUBLIC_SECOND_LEVELS:
        return None  # a bare public suffix
    return ".".join(labels[-2:])


def _is_own(host: str, domain: str) -> bool:
    host = host.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


class LinkedWebsitesConnector(BaseConnector):
    name = "websites"
    label = "Linked websites — shared TLS certificates (crt.sh) and analytics IDs (HackerTarget)"
    kind = "archive"
    homepage = "https://crt.sh"
    document_types = {"company"}
    documents_max_depth = 1
    max_retries = 1
    timeout_seconds = 25.0  # crt.sh is slow and sometimes answers 404/502 when overloaded

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY:
            return []
        docs: list[Document] = []
        for domain in websites(entity)[:2]:
            try:
                doc = self._certificates(domain)
                if doc:
                    docs.append(doc)
            except ConnectorError as exc:
                log.info("crt.sh lookup failed for %s: %s", domain, exc)
            try:
                docs.extend(self._analytics(domain))
            except ConnectorError as exc:
                log.info("analytics lookup failed for %s: %s", domain, exc)
        return docs

    # ------------------------------------------------------ certificates
    def _certificates(self, domain: str) -> Document | None:
        rows: Any = self.http_get_json(CRTSH, params={"q": f"%.{domain}", "output": "json"})
        if not rows:  # overloaded crt.sh answers 404: the identity search is lighter
            rows = self.http_get_json(CRTSH, params={"q": domain, "output": "json"})
        own = registrable_domain(domain) or domain
        found: list[str] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            names = f"{row.get('name_value') or ''}\n{row.get('common_name') or ''}"
            for name in names.split("\n"):
                reg = registrable_domain(name)
                if reg and reg != own and reg != domain and reg not in found:
                    found.append(reg)
        if not found:
            return None
        listed = ", ".join(found[:MAX_DOMAINS_LISTED])
        more = (
            f" (+{len(found) - MAX_DOMAINS_LISTED} more)" if len(found) > MAX_DOMAINS_LISTED else ""
        )
        return Document(
            title=f"Domains sharing TLS certificates with {domain}",
            kind="website",
            url=CRTSH_PAGE.format(domain=domain),
            summary=f"{len(found)} domain(s) on the same certificates: {listed}{more}",
            source="Certificate transparency (crt.sh) — shared certificates, verify the operator",
            flags=["linked_websites"],
        )

    # --------------------------------------------------------- analytics
    def _lookup(self, query: str) -> list[list[str]]:
        text = self.http_get_text(ANALYTICS, params={"q": query}) or ""
        head = text.strip().lower()
        if not head or head.startswith("error") or head.startswith("api count exceeded"):
            return []
        return [
            [p.strip() for p in line.split("\t")]
            for line in text.splitlines()
            if "\t" in line and line.strip()
        ]

    def _analytics(self, domain: str) -> list[Document]:
        ids: list[str] = []
        for parts in self._lookup(domain):
            if len(parts) >= 3 and parts[2] and parts[2] not in ids:
                ids.append(parts[2])
        docs = []
        for tracking_id in ids[:MAX_IDS]:
            try:
                rows = self._lookup(tracking_id)
            except ConnectorError:
                break  # quota or network trouble: keep what was found
            hosts: list[str] = []
            for parts in rows:
                host = parts[0].lower()
                if host and not _is_own(host, domain) and host not in hosts:
                    hosts.append(host)
            if not hosts:
                continue
            listed = ", ".join(hosts[:MAX_HOSTS_LISTED])
            more = (
                f" (+{len(hosts) - MAX_HOSTS_LISTED} more)" if len(hosts) > MAX_HOSTS_LISTED else ""
            )
            docs.append(
                Document(
                    title=f"Sites sharing the analytics ID {tracking_id}",
                    kind="website",
                    url=f"{ANALYTICS}?q={tracking_id}",
                    summary=f"ID found on {domain}; also used by: {listed}{more}",
                    source="Shared analytics IDs (HackerTarget) — possible common operator, verify",
                    flags=["linked_websites"],
                )
            )
        return docs
