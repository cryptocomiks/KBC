"""Casino Secrets — Curaçao Gaming Authority leak (2026).

https://casinosecrets.lol — an investigation by Lilith Wittmann with Follow
the Money, NDR, NRK and SVT into the offshore online gambling industry. The
consortium published a search over the companies and casino domains found in
84,000+ documents of the Curaçao Gaming Authority (licence applications),
completed with Malta, Cyprus, Gibraltar and Curaçao public registers.

Only the public search is used (one query per name, cached): company or
domain, licence holder and business type, with a link to the case file on
the site. Documents themselves (licence applications, which contain personal
identity documents) are never downloaded or stored.

Appearing in this leak does not imply wrongdoing: the licence holder,
operator or domain must be checked against the linked records.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.wayback import websites
from app.matching.names import name_similarity
from app.models import Document, Entity, EntityType, ListType, ScreeningHit

BASE = "https://casinosecrets.lol"
SEARCH = f"{BASE}/api/search.json"
DATASET = "Casino Secrets — Curaçao Gaming Authority leak (2026)"
DISCLAIMER = (
    "Leak of the Curaçao Gaming Authority published by journalists (casinosecrets.lol). "
    "Appearing in it does not imply wrongdoing."
)
MIN_NAME_SCORE = 85
MAX_SCREENED = 20


def _slug(href: str) -> str:
    """'/casinos/1451-medium-rare-n-v?tab=domains&domain=stake.com' -> '1451-medium-rare-n-v'."""
    return href.split("/casinos/", 1)[-1].split("?", 1)[0].strip("/")


class _Client(BaseConnector):
    homepage = BASE
    timeout_seconds = 8.0
    max_retries = 1

    def _search(self, query: str) -> list[dict[str, Any]]:
        if len(query.strip()) < 2:
            return []
        data = self.http_get_json(SEARCH, params={"q": query.strip()}) or {}
        return [
            r
            for r in data.get("results") or []
            if r.get("href") and (r.get("company") or r.get("name"))
        ]

    @staticmethod
    def _company_of(r: dict[str, Any]) -> str:
        return (r.get("company") or r.get("name") or "").strip()


class CasinoSecretsConnector(_Client):
    """Licence holders as searchable companies (name search, domains, link to the case file)."""

    name = "casino_secrets"
    label = "Casino Secrets — Curaçao gaming licence leak (companies & domains)"
    kind = "registry"
    crossref_max_depth = 1
    documents_max_depth = 2

    def _entity(self, company: str, results: list[dict[str, Any]]) -> Entity:
        own = [r for r in results if self._company_of(r) == company]
        slug = _slug(own[0]["href"])
        rid = self.record_id(slug)
        domains = sorted({r["name"] for r in own if r.get("type") == "domain"})
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=company,
            activity=f"Online gambling — {own[0].get('businessType') or 'licence file'} (Curaçao licensing)",
            sources=[self.provenance(rid, f"{BASE}/casinos/{slug}")],
            extra={
                k: v
                for k, v in {
                    "accounts_unknown": True,
                    "business_type": own[0].get("businessType"),
                    "casino_domains": ", ".join(domains[:10]) or None,
                    "website": domains[0] if domains else None,
                    "leak": DATASET,
                }.items()
                if v
            },
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        results = self._search(name)
        companies = list(dict.fromkeys(self._company_of(r) for r in results))
        return [self._entity(c, results) for c in companies[:8]]

    def get_company_details(self, company_id: str) -> Entity | None:
        slug = self.native_id(company_id)
        # The slug carries the name ("1451-medium-rare-n-v"): search it and keep the same file.
        words = " ".join(slug.split("-")[1:])
        for query in (words, words.rsplit(" ", 2)[0]):
            results = self._search(query)
            match = next((r for r in results if _slug(r["href"]) == slug), None)
            if match:
                return self._entity(self._company_of(match), results)
        return None

    def get_documents(self, entity: Entity) -> list[Document]:
        rid = next((r for r in entity.record_ids if r.startswith(f"{self.name}:")), None)
        if entity.type != EntityType.COMPANY or rid is None:
            return []
        slug = self.native_id(rid)
        docs = [
            Document(
                title="Casino Secrets case file (Curaçao Gaming Authority leak)",
                kind="leak",
                url=f"{BASE}/casinos/{slug}",
                summary=DISCLAIMER,
                source=self.label,
            )
        ]
        for domain in (entity.extra.get("casino_domains") or "").split(", "):
            if domain:
                docs.append(
                    Document(
                        title=f"Licensed casino domain: {domain}",
                        kind="leak",
                        url=f"{BASE}/casinos/{slug}?tab=domains&domain={domain}",
                        source=self.label,
                    )
                )
        return docs


class CasinoSecretsLeakConnector(_Client):
    """Screens every company of the network (name and official website) against the leak."""

    name = "casino_secrets_screening"
    label = "Casino Secrets — Curaçao gaming licence leak (screening)"
    kind = "leaks"

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        return self.screen_many([entity])

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        hits: list[ScreeningHit] = []
        companies = [
            e
            for e in entities
            if e.type == EntityType.COMPANY
            and not any(r.startswith("casino_secrets:") for r in e.record_ids)
        ]
        for entity in companies[:MAX_SCREENED]:
            seen: set[str] = set()
            for r in self._search(entity.name):
                company = self._company_of(r)
                score, notes = name_similarity(entity.name, company, "company")
                if score >= MIN_NAME_SCORE and company not in seen:
                    seen.add(company)
                    hits.append(
                        self._hit(entity, r, company, score, [f"company name {score:.0f}%", *notes])
                    )
            for domain in websites(entity):
                for r in self._search(domain):
                    if r.get("type") == "domain" and r.get("name", "").lower() == domain:
                        hits.append(
                            self._hit(
                                entity,
                                r,
                                self._company_of(r),
                                100.0,
                                [
                                    f"official website {domain} is a casino domain licensed to {self._company_of(r)}"
                                ],
                            )
                        )
        return hits

    def _hit(
        self, entity: Entity, r: dict[str, Any], company: str, score: float, why: list[str]
    ) -> ScreeningHit:
        slug = _slug(r["href"])
        return ScreeningHit(
            entity_id=entity.id,
            list_type=ListType.LEAK,
            dataset=DATASET,
            matched_name=company if r.get("type") != "domain" else f"{r['name']} ({company})",
            score=round(score, 1),
            explanation=why,
            details={
                "match_type": r.get("type"),
                "business_type": r.get("businessType"),
                "licence_holder": company,
                "note": DISCLAIMER,
            },
            provenance=self.provenance(self.record_id(slug), f"{BASE}{r['href']}"),
        )
