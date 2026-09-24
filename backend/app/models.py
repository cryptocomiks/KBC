"""Domain model.

Loosely aligned with the FollowTheMoney (FtM) schema used by OCCRP Aleph and
OpenSanctions, so data from those sources maps naturally. The key compliance
property: every entity, relationship and screening hit carries its provenance
(source, record id, URL, retrieval timestamp).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class EntityType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    ADDRESS = "address"
    WALLET = "wallet"  # crypto address (name = the address, chain in `chain`)


class CompanyStatus(StrEnum):
    ACTIVE = "active"
    DISSOLVED = "dissolved"
    UNKNOWN = "unknown"


class RelationType(StrEnum):
    OFFICER = "officer"  # person/company -> company (director, president, secretary...)
    SHAREHOLDER = "shareholder"  # owner -> owned company, with share_pct
    BENEFICIAL_OWNER = "beneficial_owner"  # declared UBO / PSC -> company
    REGISTERED_AT = "registered_at"  # company -> address
    CONTROLS = "controls"  # person/company -> wallet (e.g. address attributed by OFAC)
    RELATIVE = "relative"  # person <-> person: family member or close associate (PEP RCA)
    TRANSFER = "transfer"  # wallet -> wallet, aggregated on-chain flows (amount, currency)


class Provenance(BaseModel):
    """Where a piece of information comes from. Mandatory for audit trails."""

    source: str  # connector id, e.g. "pappers"
    source_label: str  # human readable, e.g. "Pappers (FR company registry)"
    record_id: str | None = None
    url: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)


_Date = date  # alias: the Document.date field would shadow the type


class Document(BaseModel):
    """A linked document / official record about an entity (filing, legal notice, register page)."""

    title: str
    kind: str  # "legal_notice", "filing", "register", "leak", "deeds", "accounts"...
    date: _Date | None = None
    url: str | None = None
    summary: str | None = None
    source: str  # connector label, or "Official register link"
    flags: list[str] = Field(default_factory=list)  # e.g. ["insolvency"]


class Entity(BaseModel):
    id: str  # "<connector>:<native id>" for raw records, canonical id once resolved
    type: EntityType
    name: str
    aliases: list[str] = Field(default_factory=list)

    # Person attributes
    birth_date: str | None = None  # "YYYY", "YYYY-MM" or "YYYY-MM-DD" (registries often truncate)
    nationalities: list[str] = Field(default_factory=list)  # ISO 3166-1 alpha-2

    # Company attributes
    jurisdiction: str | None = None  # ISO 3166-1 alpha-2
    registration_number: str | None = None
    legal_form: str | None = None
    status: CompanyStatus | None = None
    incorporation_date: date | None = None
    dissolution_date: date | None = None
    last_accounts_date: date | None = None
    activity: str | None = None

    address: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    is_offshore: bool = False
    chain: str | None = None  # "BTC", "ETH", "TRON" for wallets
    demo: bool = False  # fictitious record (demo dataset)

    documents: list[Document] = Field(default_factory=list)  # linked filings / notices / registers
    # raw source records merged into this entity
    record_ids: list[str] = Field(default_factory=list)
    sources: list[Provenance] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("incorporation_date", "dissolution_date", "last_accounts_date", mode="before")
    @classmethod
    def _exact_dates_only(cls, value: Any) -> Any:
        """Sources sometimes give only a year or a year-month: never fail on it,
        keep the field empty rather than invent a day."""
        if isinstance(value, str) and len(value.strip()) < 10:
            return None
        return value

    @property
    def is_company(self) -> bool:
        return self.type == EntityType.COMPANY


class Relationship(BaseModel):
    id: str
    type: RelationType
    source_id: str  # holder / officer / company (arrow origin)
    target_id: str  # company / address (arrow target)
    role: str | None = None
    share_pct: float | None = None
    # On-chain transfers (aggregated between two wallets)
    amount: float | None = None
    currency: str | None = None
    tx_count: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    sources: list[Provenance] = Field(default_factory=list)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _exact_dates_only(cls, value: Any) -> Any:
        if isinstance(value, str) and len(value.strip()) < 10:
            return None
        return value

    @property
    def is_active(self) -> bool:
        return self.end_date is None


class LinkedEntity(BaseModel):
    """A relationship together with the entity at its other end, as returned by connectors."""

    relationship: Relationship
    entity: Entity


class ListType(StrEnum):
    SANCTION = "sanction"
    PEP = "pep"
    LEAK = "leak"
    ADVERSE = "adverse"


class ScreeningHit(BaseModel):
    entity_id: str  # entity of the network that was screened
    list_type: ListType
    dataset: str
    matched_name: str
    score: float  # 0-100 confidence
    explanation: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class MatchResult(BaseModel):
    score: float
    explanation: list[str]
    #: structured signals behind the score, e.g. {"dob": "match" | "partial" | "conflict"}
    signals: dict[str, Any] = Field(default_factory=dict)


class SearchCandidate(BaseModel):
    """A disambiguation candidate shown to the analyst after a search."""

    entity: Entity
    score: float
    explanation: list[str]
    linked_companies: list[str] = Field(default_factory=list)
    roles_count: int = 0
