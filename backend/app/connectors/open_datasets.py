"""Open watchlists downloaded as bulk files (no API key).

EU, UK and Swiss sanctions, World Bank debarments and Interpol red notices,
from the normalised bulk exports published by OpenSanctions
(https://www.opensanctions.org/datasets/ — `targets.simple.csv`). The same
format for every list keeps parsing reliable. The files are downloaded once
per server instance (refreshed every 12 h) and indexed by name.

Licence: OpenSanctions data is CC BY-NC 4.0 — free for non-commercial use
(this portfolio project); commercial use requires a licence.
"""

from __future__ import annotations

import csv
import io
import threading
import time

import httpx

from app.connectors.base import USER_AGENT, BaseConnector, ConnectorError
from app.connectors.official_sanctions import ListedEntry, _Index
from app.matching.matcher import match_entities
from app.models import Entity, EntityType, ListType, ScreeningHit

URL = "https://data.opensanctions.org/datasets/latest/{dataset}/targets.simple.csv"
ENTITY_URL = "https://www.opensanctions.org/entities/{id}/"
REFRESH_SECONDS = 12 * 3600
MIN_SCORE = 60

DATASETS = {
    "eu_fsf": ("EU Financial Sanctions Files (consolidated list)", ListType.SANCTION),
    "gb_hmt_sanctions": ("UK financial sanctions (HM Treasury / OFSI)", ListType.SANCTION),
    "ch_seco_sanctions": ("Swiss sanctions (SECO)", ListType.SANCTION),
    "worldbank_debarred": ("World Bank debarred firms and individuals", ListType.ADVERSE),
    "interpol_red_notices": ("Interpol red notices (public)", ListType.ADVERSE),
}
SKIPPED_SCHEMAS = {"Vessel", "Airplane", "CryptoWallet", "Address", "Security"}


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(";") if v.strip()]


class _State:
    def __init__(self) -> None:
        self.index = _Index()
        self.loaded_at = 0.0
        self.errors: list[str] = []
        self.lock = threading.Lock()


_STATE = _State()


def _load(dataset: str, index: _Index, timeout: float) -> None:
    label, list_type = DATASETS.get(dataset, (dataset, ListType.SANCTION))
    resp = httpx.get(
        URL.format(dataset=dataset),
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8", errors="replace"))):
        schema = row.get("schema") or ""
        if schema in SKIPPED_SCHEMAS or not row.get("name"):
            continue
        is_person = schema == "Person"
        dobs = _split(row.get("birth_date"))
        countries = [c.upper() for c in _split(row.get("countries")) if len(c) == 2]
        entity = Entity(
            id=f"{dataset}:{row.get('id')}",
            type=EntityType.PERSON if is_person else EntityType.COMPANY,
            name=row["name"],
            aliases=_split(row.get("aliases"))[:30],
            birth_date=dobs[0] if dobs and is_person else None,
            nationalities=countries if is_person else [],
            jurisdiction=countries[0] if countries and not is_person else None,
        )
        index.add(
            ListedEntry(
                entity=entity,
                dataset=label,
                url=ENTITY_URL.format(id=row.get("id")),
                program=(_split(row.get("sanctions")) or [None])[0],
                details={
                    "countries": ", ".join(countries) or None,
                    "first_seen": row.get("first_seen") or None,
                },
                list_type=list_type,
            )
        )


class OpenDatasetsConnector(BaseConnector):
    name = "open_watchlists"
    label = "EU / UK / Swiss sanctions, World Bank debarments, Interpol red notices"
    kind = "screening"
    homepage = "https://www.opensanctions.org/datasets/"

    def _datasets(self) -> list[str]:
        return [d.strip() for d in self.settings.open_datasets.split(",") if d.strip()]

    def _index(self) -> _Index:
        with _STATE.lock:
            if not _STATE.index.entries or time.time() - _STATE.loaded_at > REFRESH_SECONDS:
                fresh, errors = _Index(), []
                timeout = max(self.settings.http_timeout_seconds, 30.0)
                for dataset in self._datasets():
                    try:
                        _load(dataset, fresh, timeout)
                    except (httpx.HTTPError, csv.Error, ValueError) as exc:
                        errors.append(f"{dataset} unavailable ({exc})")
                if not fresh.entries:
                    raise ConnectorError(f"{self.label}: " + "; ".join(errors or ["no data"]))
                _STATE.index, _STATE.errors, _STATE.loaded_at = fresh, errors, time.time()
            return _STATE.index

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type not in (EntityType.PERSON, EntityType.COMPANY):
            return []
        hits = []
        for entry in self._index().candidates(entity):
            result = match_entities(entity, entry.entity)
            if result.score < MIN_SCORE:
                continue
            listed = entry.entity
            hits.append(
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=entry.list_type,
                    dataset=entry.dataset,
                    matched_name=listed.name,
                    score=result.score,
                    explanation=result.explanation,
                    details={
                        "program": entry.program,
                        "birth_date": listed.birth_date,
                        "nationalities": listed.nationalities or None,
                        **entry.details,
                        "source": "OpenSanctions bulk data (CC BY-NC 4.0)",
                    },
                    provenance=self.provenance(self.record_id(listed.id), entry.url),
                )
            )
        return hits

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        return [h for e in entities for h in self.screen(e)]
