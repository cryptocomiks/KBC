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
import threading
import time
from abc import ABC
from typing import Any, ClassVar

import httpx

from app.cache import get_cache
from app.models import Document, Entity, LinkedEntity, Provenance, ScreeningHit, utcnow
from app.settings import Settings, get_settings

log = logging.getLogger(__name__)

USER_AGENT = "KYC1Click/0.3 (+https://github.com/cryptocomiks/KBC)"
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.8

# One pacing lock per source: requests made in parallel still respect its rate limit.
_PACE_LOCKS: dict[str, threading.Lock] = {}
_LAST_CALL: dict[str, float] = {}
_PACE_GUARD = threading.Lock()


def _pace(name: str, interval: float) -> None:
    if interval <= 0:
        return
    with _PACE_GUARD:
        lock = _PACE_LOCKS.setdefault(name, threading.Lock())
    with lock:
        wait = _LAST_CALL.get(name, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[name] = time.monotonic()


class ConnectorError(RuntimeError):
    pass


# Circuit breaker: a source that cannot be reached (DNS failure, connection refused,
# repeated timeouts, rate limit) is skipped for a few minutes instead of being called:
# and reported: for every entity of the investigation.
_DOWN: dict[str, tuple[float, str]] = {}
_DOWN_GUARD = threading.Lock()
DOWN_SECONDS = {"unreachable": 300.0, "rate limited": 120.0}


def _mark_down(name: str, reason: str) -> None:
    with _DOWN_GUARD:
        _DOWN[name] = (time.monotonic() + DOWN_SECONDS.get(reason, 120.0), reason)


def _down_reason(name: str) -> str | None:
    with _DOWN_GUARD:
        until, reason = _DOWN.get(name, (0.0, ""))
        if until > time.monotonic():
            return reason
        _DOWN.pop(name, None)
        return None


def reset_circuit_breakers() -> None:
    """Tests: forget the sources marked as down."""
    with _DOWN_GUARD:
        _DOWN.clear()


def group_warnings(warnings: list[str]) -> list[str]:
    """One line per problem: repeated messages from the same source are counted, not repeated."""
    counts: dict[str, int] = {}
    for w in warnings:
        counts[w] = counts.get(w, 0) + 1
    by_source: dict[str, list[str]] = {}
    for w in counts:
        source = w.split(": ", 1)[0] if ": " in w else w
        by_source.setdefault(source, []).append(w)
    out = []
    for messages in by_source.values():
        total = sum(counts[m] for m in messages)
        # the root cause first, not the "skipped" follow-ups
        first = next((m for m in messages if "skipped for a few minutes" not in m), messages[0])
        out.append(first + (f" (×{total})" if total > 1 else ""))
    return out


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
    #: minimum delay between two requests to the source (its published rate limit)
    min_interval_seconds: ClassVar[float] = 0.0
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
        if self.blocked_by_licence:
            return (
                False,
                "Disabled in commercial mode: non-commercial licence (add it to LICENSED_SOURCES once licensed)",
            )
        return True, "Enabled" + ("" if self.key_setting else " (public API, no key required)")

    @property
    def licence(self) -> tuple[str, str, str]:
        """(category, licence, note): see app.licences."""
        from app.licences import licence_of

        return licence_of(self.name, self.is_demo)

    @property
    def blocked_by_licence(self) -> bool:
        from app.licences import licensed_names

        return (
            self.settings.commercial_mode
            and self.licence[0] == "non_commercial"
            and self.name not in licensed_names(self.settings.licensed_sources)
        )

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
        cache: bool = True,
    ) -> Any:
        """GET with SQLite caching, so the same query never hits the API twice (cache=False for
        ephemeral answers: session tokens, results still being prepared)."""
        return self._request("GET", url, params=params, headers=headers, auth=auth, use_cache=cache)

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
        cache: bool = True,
    ) -> Any:
        """POST (JSON or form body) with the same caching and retry policy."""
        return self._request(
            "POST",
            url,
            params=params,
            headers=headers,
            json_body=json_body,
            form=form,
            use_cache=cache,
        )

    def http_post_text(
        self, url: str, content: str, headers: dict[str, str] | None = None
    ) -> str | None:
        """POST a raw body (e.g. a SOAP envelope) and return the response text, cached."""
        return self._request("POST", url, headers=headers, content=content, as_text=True)

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
        content: str | None = None,
        as_text: bool = False,
        use_cache: bool = True,
    ) -> Any:
        cache = get_cache()
        key_material = json.dumps(
            [method, url, sorted((params or {}).items()), json_body, form, content, as_text],
            default=str,
        )
        key = hashlib.sha256(key_material.encode()).hexdigest()
        cached = cache.get(f"http:{self.name}", key) if use_cache else None
        if cached is not None:
            return cached
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*" if as_text else "application/json",
            **(headers or {}),
        }
        down = _down_reason(self.name)
        if down:
            raise ConnectorError(f"{self.label}: {down}, skipped for a few minutes")
        resp = None
        retries = self.max_retries
        for attempt in range(retries + 1):
            _pace(self.name, self.min_interval_seconds)
            try:
                resp = httpx.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    auth=auth,
                    json=json_body,
                    data=form,
                    content=content.encode() if content is not None else None,
                    timeout=self.timeout_seconds or self.settings.http_timeout_seconds,
                    follow_redirects=True,
                )
            except httpx.HTTPError as exc:
                if attempt < retries:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
                # cannot connect (refused or connection timed out): skip the source for a while
                # instead of waiting again for every entity of the investigation
                if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
                    _mark_down(self.name, "unreachable")
                    raise ConnectorError(
                        f"{self.label}: source unreachable ({exc}), skipped for this investigation"
                    ) from exc
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
            if self.key_setting:
                raise ConnectorError(
                    f"{self.label}: access refused (HTTP {resp.status_code}), check the API key"
                )
            # A keyless source that refuses us (bot protection, blocked cloud address): let it
            # rest instead of asking again for every entity.
            _mark_down(self.name, "access refused by the source")
            raise ConnectorError(
                f"{self.label}: access refused by the source (HTTP {resp.status_code})"
            )
        elif resp.status_code == 429:
            _mark_down(self.name, "rate limited")
            raise ConnectorError(f"{self.label}: rate limited by the source (HTTP 429)")
        elif resp.status_code >= 400:
            raise ConnectorError(f"{self.label}: HTTP {resp.status_code}")
        elif as_text:
            data = resp.text
        else:
            try:
                data = resp.json()
            except ValueError as exc:
                raise ConnectorError(f"{self.label}: invalid JSON response") from exc
        if use_cache:
            cache.set(f"http:{self.name}", key, data)
        return data
