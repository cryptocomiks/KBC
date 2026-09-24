"""Recursive network expansion with cross-source resolution.

Breadth-first expansion from the subject:

* depth d < max_depth: every link of the node is followed and new entities
  are added (until `max_nodes` is reached -> the result is flagged as truncated);
* depth d == max_depth (frontier): links are fetched only to *close* edges
  between entities already in the network (e.g. to reveal a circular
  shareholding), no new node is added.

Each new company/person is cross-referenced against the other registries so
that the same entity seen in two sources becomes a single node with two
provenances. Every connector call is logged (sources consulted table).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, Field

from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.registry import ConnectorRegistry
from app.graph.links import register_links
from app.graph.resolver import EntityResolver, address_entity
from app.models import (
    Entity,
    EntityType,
    LinkedEntity,
    Relationship,
    RelationType,
    ScreeningHit,
    utcnow,
)
from app.risk.config import get_jurisdictions


class QueryLog(BaseModel):
    source: str
    source_label: str
    operation: str
    target: str
    results: int = 0
    error: str | None = None
    retrieved_at: Any = Field(default_factory=utcnow)


class Network(BaseModel):
    subject_id: str
    max_depth: int
    max_nodes: int
    entities: dict[str, Entity] = Field(default_factory=dict)
    relationships: dict[str, Relationship] = Field(default_factory=dict)
    depth: dict[str, int] = Field(default_factory=dict)
    hits: list[ScreeningHit] = Field(default_factory=list)
    queries: list[QueryLog] = Field(default_factory=list)
    merges: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False


class NetworkExpander:
    def __init__(
        self,
        registry: ConnectorRegistry,
        max_depth: int = 2,
        max_nodes: int = 60,
        time_budget: float | None = None,
    ) -> None:
        self.registry = registry
        self.time_budget = time_budget or registry.settings.expansion_time_budget_seconds
        self.demo_realm = False
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.resolver = EntityResolver()
        self.depth: dict[str, int] = {}
        self.relationships: dict[str, Relationship] = {}
        self.queries: list[QueryLog] = []
        self.warnings: list[str] = []
        self.truncated = False
        self._crossrefd: set[str] = set()

    # ------------------------------------------------------------ utilities
    def _call(self, conn: BaseConnector, operation: str, target: str, fn: Callable, *args: Any):
        log = QueryLog(
            source=conn.name, source_label=conn.label, operation=operation, target=target
        )
        self.queries.append(log)
        try:
            result = fn(*args)
        except ConnectorError as exc:
            log.error = str(exc)
            self.warnings.append(str(exc))
            return [] if operation != "get_details" else None
        log.results = len(result) if isinstance(result, list) else int(result is not None)
        return result

    @property
    def entities(self) -> dict[str, Entity]:
        return self.resolver.entities

    def _node_count(self) -> int:
        return len(self.entities)

    def _add_entity(self, entity: Entity, depth: int, allow_new: bool) -> str | None:
        cid, _, _ = self.resolver.find(entity)
        if cid is None:
            if not allow_new:
                return None
            if self._node_count() >= self.max_nodes:
                self.truncated = True
                return None
        cid, created = self.resolver.add(entity)
        if created:
            self.depth[cid] = depth
            self._decorate(self.entities[cid])
        else:
            self.depth[cid] = min(self.depth.get(cid, depth), depth)
        return cid

    def _decorate(self, entity: Entity) -> None:
        if entity.type == EntityType.COMPANY and entity.jurisdiction:
            entity.is_offshore = entity.jurisdiction.upper() in get_jurisdictions().offshore_centres

    def _add_relationship(self, rel: Relationship, src: str, tgt: str) -> None:
        key = f"{rel.type}|{src}|{tgt}"
        if rel.type == RelationType.OFFICER and rel.end_date:
            key += f"|{rel.end_date}"
        existing = self.relationships.get(key)
        if existing is None:
            self.relationships[key] = rel.model_copy(
                update={"id": key, "source_id": src, "target_id": tgt}
            )
            return
        known_urls = {(p.source, p.record_id) for p in existing.sources}
        existing.sources.extend(p for p in rel.sources if (p.source, p.record_id) not in known_urls)
        if rel.role and existing.role and rel.role.casefold() not in existing.role.casefold():
            existing.role = f"{existing.role} / {rel.role}"
        existing.role = existing.role or rel.role
        if existing.share_pct is None:
            existing.share_pct = rel.share_pct

    def _records_by_connector(self, cid: str) -> list[tuple[BaseConnector, str]]:
        out = []
        for rid in self.entities[cid].record_ids:
            conn = self.registry.for_record(rid)
            if conn and conn.kind == "registry" and conn.is_demo == self.demo_realm:
                out.append((conn, rid))
        return out

    # ------------------------------------------------------- cross-reference
    def _cross_reference(self, cid: str) -> None:
        """Look the entity up in the other registries and merge confirmed matches."""
        if cid in self._crossrefd:
            return
        self._crossrefd.add(cid)
        entity = self.entities[cid]
        if entity.type == EntityType.ADDRESS:
            return
        have = {rid.split(":", 1)[0] for rid in entity.record_ids}
        for conn in self.registry.enabled("registry", demo=self.demo_realm):
            if conn.name in have:
                continue
            if entity.type == EntityType.COMPANY:
                if not conn.covers(entity.jurisdiction):
                    continue
                found = self._call(
                    conn, "search_company", entity.name, conn.search_company, entity.name
                )
            else:
                found = self._call(
                    conn, "search_person", entity.name, conn.search_person, entity.name
                )
            for cand in found or []:
                ok, _, _ = self.resolver.same_entity(entity, cand)
                if ok:
                    self.resolver.add(cand)  # merges into `cid` and logs the merge

    # -------------------------------------------------------------- links
    def _fetch_links(self, cid: str) -> list[LinkedEntity]:
        entity = self.entities[cid]
        links: list[LinkedEntity] = []
        for conn, rid in self._records_by_connector(cid):
            if entity.type == EntityType.COMPANY:
                if entity.extra.get("accounts_unknown") or entity.incorporation_date is None:
                    # Partial record (found via a search or an appointment): fetch the full profile.
                    detail = self._call(
                        conn, "get_details", entity.name, conn.get_company_details, rid
                    )
                    if detail is not None:
                        self.resolver.add(detail)
                links += self._call(conn, "get_officers", entity.name, conn.get_officers, rid)
                links += self._call(
                    conn, "get_shareholders", entity.name, conn.get_shareholders, rid
                )
                links += self._call(
                    conn, "get_subsidiaries", entity.name, conn.get_subsidiaries, rid
                )
            elif entity.type == EntityType.PERSON:
                links += self._call(
                    conn, "get_person_roles", entity.name, conn.get_person_roles, rid
                )
        return links

    def _address_links(self, cid: str, depth: int) -> None:
        """Company -> registered address node, plus domiciliation count."""
        entity = self.entities[cid]
        if entity.type != EntityType.COMPANY or not entity.address:
            return
        addr = address_entity(entity.address, demo=entity.demo)
        aid = self._add_entity(addr, depth + 1, allow_new=depth < self.max_depth)
        if aid is None:
            return
        rel = Relationship(
            id=f"addr|{cid}|{aid}",
            type=RelationType.REGISTERED_AT,
            source_id=cid,
            target_id=aid,
            role="Registered office",
            sources=entity.sources[:1],
        )
        self._add_relationship(rel, cid, aid)
        address = self.entities[aid]
        if "companies_registered" not in address.extra:
            names: set[str] = set()
            for conn in self.registry.enabled("registry", demo=self.demo_realm):
                found = self._call(
                    conn, "search_address", address.name, conn.search_address, address.name
                )
                names |= {c.registration_number or c.name for c in found or []}
            address.extra["companies_registered"] = len(names)

    def _expand_address(self, aid: str, depth: int) -> None:
        address = self.entities[aid]
        for conn in self.registry.enabled("registry", demo=self.demo_realm):
            for company in self._call(
                conn, "search_address", address.name, conn.search_address, address.name
            ):
                ccid = self._add_entity(company, depth + 1, allow_new=depth < self.max_depth)
                if ccid:
                    rel = Relationship(
                        id=f"addr|{ccid}|{aid}",
                        type=RelationType.REGISTERED_AT,
                        source_id=ccid,
                        target_id=aid,
                        role="Registered office",
                        sources=company.sources[:1],
                    )
                    self._add_relationship(rel, ccid, aid)

    # --------------------------------------------------------------- main
    def expand(self, seeds: list[Entity]) -> Network:
        if not seeds:
            raise ValueError("no seed entity")
        # Investigations stay within one realm: fictitious demo data or real data.
        self.demo_realm = seeds[0].demo
        started = time.monotonic()
        subject_id = None
        for seed in seeds:  # several records of the same subject (already deduplicated by search)
            cid, _ = self.resolver.add(seed)
            subject_id = subject_id or cid
        assert subject_id is not None
        self.depth[subject_id] = 0
        self._decorate(self.entities[subject_id])
        self._cross_reference(subject_id)

        queue: deque[str] = deque([subject_id])
        expanded: set[str] = set()
        while queue:
            if time.monotonic() - started > self.time_budget:
                self.truncated = True
                self.warnings.append(
                    f"Time budget of {self.time_budget:.0f}s reached: {len(queue)} node(s) were not expanded. "
                    "Reduce the depth or rerun (results are cached)."
                )
                break
            cid = queue.popleft()
            if cid in expanded:
                continue
            expanded.add(cid)
            depth = self.depth[cid]
            allow_new = depth < self.max_depth
            entity = self.entities[cid]

            if entity.type == EntityType.ADDRESS:
                if allow_new:
                    self._expand_address(cid, depth)
                continue

            links = self._fetch_links(cid)
            if entity.type == EntityType.PERSON:
                entity.extra["active_mandates"] = len(
                    {
                        link.entity.id
                        for link in links
                        if link.relationship.type == RelationType.OFFICER
                        and link.relationship.is_active
                    }
                )
            for link in links:
                rel = link.relationship
                other_cid = self._add_entity(link.entity, depth + 1, allow_new)
                if other_cid is None:
                    continue
                if other_cid not in expanded:
                    self._cross_reference(other_cid)
                    queue.append(other_cid)
                # Map raw record ids to canonical ids for both ends.
                src = self.resolver.canonical_of(rel.source_id) or rel.source_id
                tgt = self.resolver.canonical_of(rel.target_id) or rel.target_id
                if src in self.entities and tgt in self.entities:
                    self._add_relationship(rel, src, tgt)
            self._address_links(cid, depth)
            for aid in [
                r.target_id
                for r in self.relationships.values()
                if r.type == RelationType.REGISTERED_AT and r.source_id == cid
            ]:
                if aid not in expanded:
                    queue.append(aid)

        if self.truncated and not any("Time budget" in w for w in self.warnings):
            self.warnings.append(
                f"Node limit of {self.max_nodes} reached: the network was truncated. "
                "Increase the limit or reduce the depth to see more."
            )
        self._collect_documents()
        hits = self._screen()
        return Network(
            subject_id=subject_id,
            max_depth=self.max_depth,
            max_nodes=self.max_nodes,
            entities=self.entities,
            relationships=self.relationships,
            depth=self.depth,
            hits=hits,
            queries=self.queries,
            merges=self.resolver.merges,
            warnings=self.warnings,
            truncated=self.truncated,
        )

    # ---------------------------------------------------------- screening
    def _collect_documents(self) -> None:
        """Linked documents (legal notices, filings, register pages) for every company."""
        companies = [e for e in self.entities.values() if e.type == EntityType.COMPANY]
        providers = [
            c
            for c in self.registry.enabled(demo=self.demo_realm)
            if type(c).get_documents is not BaseConnector.get_documents
        ]
        tasks = [(conn, e) for e in companies for conn in providers if conn.covers(e.jurisdiction)]

        def run(task: tuple[BaseConnector, Entity]) -> tuple[Entity, list]:
            conn, entity = task
            return entity, self._call(
                conn, "get_documents", entity.name, conn.get_documents, entity
            ) or []

        found: dict[str, list] = {e.id: [] for e in companies}
        if tasks:
            workers = max(1, min(self.registry.settings.screening_workers, len(tasks)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for entity, docs in pool.map(run, tasks):
                    found[entity.id].extend(docs)
        for entity in companies:
            seen: set[tuple] = set()
            merged = []
            for doc in [*found[entity.id], *register_links(entity)]:
                key = (doc.url, doc.title)
                if key not in seen:
                    seen.add(key)
                    merged.append(doc)
            # Dated records first (most recent on top), then register links.
            entity.documents = sorted(
                merged, key=lambda d: (d.date is None, -(d.date.toordinal() if d.date else 0))
            )

    def _screen(self) -> list[ScreeningHit]:
        """Screen every person/company against sanctions, PEP and leak sources, in parallel."""
        entities = [e for e in self.entities.values() if e.type != EntityType.ADDRESS]
        screeners = [
            c
            for c in self.registry.enabled(demo=self.demo_realm)
            if c.kind in ("screening", "leaks")
        ]
        tasks: list[tuple[BaseConnector, list[Entity]]] = []
        for conn in screeners:
            batched = type(conn).screen_many is not BaseConnector.screen_many
            tasks += [(conn, entities)] if batched else [(conn, [e]) for e in entities]

        def run(task: tuple[BaseConnector, list[Entity]]) -> list[ScreeningHit]:
            conn, batch = task
            target = batch[0].name if len(batch) == 1 else f"{len(batch)} entities"
            return self._call(conn, "screen", target, conn.screen_many, batch) or []

        hits: dict[tuple, ScreeningHit] = {}
        workers = max(1, min(self.registry.settings.screening_workers, len(tasks) or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(run, tasks):
                for hit in result:
                    key = (hit.entity_id, hit.dataset, hit.provenance.record_id)
                    if key not in hits or hits[key].score < hit.score:
                        hits[key] = hit
        return sorted(hits.values(), key=lambda h: (-h.score, h.entity_id))
