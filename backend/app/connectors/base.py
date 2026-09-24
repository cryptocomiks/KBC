"""Common connector interface.

Every data source (registry, sanctions list, leak database) implements the
same interface so that new sources (e.g. Zefix for Switzerland, RCS/LBR for
Luxembourg) can be plugged in without touching the rest of the pipeline.

Methods that make no sense for a given source simply return an empty result.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC
from typing import Any, ClassVar

import httpx

from app.cache import get_cache
from app.models import Document, Entity, LinkedEntity, Provenance, ScreeningHit, utcnow
from app.settings import Settings, get_settings

log = logging.getLogger(__name__)

USER_AGENT = "KBC-CorporateMapping/0.2 (+https://github.com/cryptocomiks/KBC)"
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.8


class ConnectorError(RuntimeError):
    pass


class BaseConnector(ABC):
    #: stable identifier, used as record id prefix ("pappers:552100554")
    name: ClassVar[str]
    #: human-readable label shown in the UI and in reports
    label: ClassVar[str]
    #: "registry" (companies/officers), "screening" (sanctions/PEP) or "leaks"
    kind: ClassVar[str] = "registry"
    #: settings attribute holding the API key, None if no key is required
    key_setting: ClassVar[str | None] = None
    #: ISO-2 jurisdictions covered by a registry (None = worldwide)
    jurisdictions: ClassVar[set[str] | None] = None
    #: True for connectors serving the fictitious demo dataset
    is_demo: ClassVar[bool] = False
    homepage: ClassVar[str | None] = None
    #: only cross-reference entities up to this distance from the subject (slow sources)
    crossref_max_depth: ClassVar[int | None] = None
    #: retries on rate limits / transient errors (0 for sources that ask clients not to retry)
    max_retries: ClassVar[int] = MAX_RETRIES
    #: per-connector HTTP timeout in seconds (None = settings.http_timeout_seconds)
    timeout_seconds: ClassVar[float | None] = None
    #: documents: entity types handled and maximum distance from the subject
    document_types: ClassVar[set[str]] = {"company"}
    documents_max_depth: ClassVar[int | None] = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ status
    @property
    def api_key(self) -> str:
        return getattr(self.settings, self.key_setting, "") if self.key_setting else ""

    def status(self) -> tuple[bool, str]:
        """(enabled, message). A missing key disables the connector with a clear message."""
        if self.is_demo:
            if self.settings.demo_mode:
                return True, "Demo mode: fictitious dataset"
            return False, "Disabled (DEMO_MODE=false)"
        if not self.settings.live_sources:
            return False, "Disabled (LIVE_SOURCES=false)"
        if self.key_setting and not self.api_key:
            return False, f"Disabled: {self.key_setting.upper()} is not set"
        return True, "Enabled" + ("" if self.key_setting else " (public API, no key required)")

    @property
    def enabled(self) -> bool:
        return self.status()[0]

    def covers(self, jurisdiction: str | None) -> bool:
        return self.jurisdictions is None or (jurisdiction or "").upper() in self.jurisdictions

    # -------------------------------------------------------------- interface
    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        return []

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return []

    def get_company_details(self, company_id: str) -> Entity | None:
        return None

    def get_person_details(self, person_id: str) -> Entity | None:
        return None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        """People/companies holding a position in the company (incl. past ones)."""
        return []

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        """Direct shareholders and declared beneficial owners (UBO / PSC)."""
        return []

    # Optional extensions used by the network expansion
    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        """Mandates and holdings of a person (relationship target = company)."""
        return []

    def get_subsidiaries(self, company_id: str) -> list[LinkedEntity]:
        """Companies in which the company holds shares."""
        return []

    # Crypto extensions (wallets are entities of type "wallet")
    def get_wallet(self, address: str) -> Entity | None:
        """Wallet profile (balance, activity) for an address on the connector's chain."""
        return None

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        """Crypto links of an entity: aggregated on-chain transfers of a wallet
        (counterparties) and/or wallets controlled by / controlling the entity."""
        return []

    def get_documents(self, entity: Entity) -> list[Document]:
        """Documents / official records about an entity (filings, legal notices...)."""
        return []

    def get_by_identifier(self, ident: Any) -> Entity | None:
        """Exact lookup by a company identifier (app.identifiers.Identifier). None if unsupported."""
        return None

    def search_address(self, address: str) -> list[Entity]:
        """Companies registered at an address (detects domiciliation hubs)."""
        return []

    def prefetch(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Start slow downloads in the background (called when an investigation starts)."""

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        """Sanctions / PEP / leaks screening of an entity."""
        return []

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        """Batch screening; override when the source accepts batched queries."""
        hits: list[ScreeningHit] = []
        for entity in entities:
            hits.extend(self.screen(entity))
        return hits

    # ---------------------------------------------------------------- helpers
    def native_id(self, record_id: str) -> str:
        prefix = f"{self.name}:"
        return record_id[len(prefix) :] if record_id.startswith(prefix) else record_id

    def record_id(self, native_id: str) -> str:
        return f"{self.name}:{native_id}"

    def provenance(self, record_id: str | None = None, url: str | None = None) -> Provenance:
        return Provenance(
            source=self.name,
            source_label=self.label,
            record_id=record_id,
            url=url,
            retrieved_at=utcnow(),
        )

    def http_get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> Any:
        """GET with SQLite caching, so the same query never hits the API twice."""
        return self._request("GET", url, params=params, headers=headers, auth=auth)

    def http_get_text(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> str | None:
        """GET a non-JSON document (XML, HTML) with the same caching and retry policy."""
        return self._request("GET", url, params=params, headers=headers, as_text=True)

    def http_post_json(
        self,
        url: str,
        json_body: Any = None,
        form: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """POST (JSON or form body) with the same caching and retry policy."""
        return self._request(
            "POST", url, params=params, headers=headers, json_body=json_body, form=form
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        json_body: Any = None,
        form: dict[str, str] | None = None,
        as_text: bool = False,
    ) -> Any:
        cache = get_cache()
        key_material = json.dumps(
            [method, url, sorted((params or {}).items()), json_body, form, as_text], default=str
        )
        key = hashlib.sha256(key_material.encode()).hexdigest()
        cached = cache.get(f"http:{self.name}", key)
        if cached is not None:
            return cached
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*" if as_text else "application/json",
            **(headers or {}),
        }
        resp = None
        retries = self.max_retries
        for attempt in range(retries + 1):
            try:
                resp = httpx.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    auth=auth,
                    json=json_body,
                    data=form,
                    timeout=self.timeout_seconds or self.settings.http_timeout_seconds,
                    follow_redirects=True,
                )
            except httpx.HTTPError as exc:
                if attempt < retries:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
                raise ConnectorError(f"{self.label}: network error ({exc})") from exc
            # Rate limited or transient server error: back off and retry.
            if resp.status_code in (429, 502, 503, 504) and attempt < retries:
                retry_after = resp.headers.get("Retry-After", "")
                delay = (
                    float(retry_after)
                    if retry_after.isdigit()
                    else RETRY_BACKOFF_SECONDS * (2**attempt)
                )
                time.sleep(min(delay, 5.0))
                continue
            break
        assert resp is not None
        if resp.status_code == 404:
            data: Any = None
        elif resp.status_code in (401, 403):
            raise ConnectorError(
                f"{self.label}: access refused (HTTP {resp.status_code}) — check the API key"
            )
        elif resp.status_code >= 400:
            raise ConnectorError(f"{self.label}: HTTP {resp.status_code}")
        elif as_text:
            data = resp.text
        else:
            try:
                data = resp.json()
            except ValueError as exc:
                raise ConnectorError(f"{self.label}: invalid JSON response") from exc
        cache.set(f"http:{self.name}", key, data)
        return data
