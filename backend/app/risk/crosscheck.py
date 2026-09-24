"""Cross-checks between the parties of a network: service providers and timing.

These patterns come from investigative practice (ICIJ, OCCRP, FATF typologies on
the misuse of legal persons): the same formation agent or corporate director
behind many companies, companies created in batches, officers resigning just
before a liquidation, people holding mandates across many jurisdictions, and
namesakes that may be the same person in two registries. Each finding is a lead
to verify, with its evidence, never a conclusion.
"""

from __future__ import annotations

import contextlib
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import date

from rapidfuzz import fuzz
from unidecode import unidecode

from app.graph.expander import Network
from app.models import CompanyStatus, EntityType, RelationType

# Registered agents / corporate service providers that recur in offshore leaks
# (ICIJ Offshore Leaks "intermediaries", OCCRP investigations). Presence is a lead,
# not a wrongdoing: most of their clients are legitimate.
FORMATION_AGENTS = (
    "mossack fonseca",
    "trident trust",
    "portcullis",
    "commonwealth trust",
    "asiaciti",
    "aleman cordero galindo",
    "alcogal",
    "fidelity corporate services",
    "il shin",
    "appleby",
    "estera",
    "ocra",
    "offshore company registration agents",
    "vistra",
    "intertrust",
    "sovereign trust",
    "sfm corporate",
    "morgan & morgan",
    "morgan y morgan",
    "overseas management company",
    "ansbacher",
    "rawlinson & hunter",
    "credit suisse trust",
    "ubs trustees",
    "equity trust",
    "tmf group",
    "citco",
    "maples corporate services",
    "walkers corporate",
    "conyers",
    "harneys",
    "ogier",
    "mourant",
    "codan trust",
    "abacus trust",
    "circle corporate services",
    "zedra",
    "amicorp",
    "sterling trust",
    "cititrust",
)
CORPORATE_OFFICER_ROLES = re.compile(
    r"director|secretary|nominee|administrat|manager|g[ée]rant", re.I
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9& ]+", " ", unidecode(name).lower()).strip()


def cross_checks(net: Network, t: dict, flag: Callable[[str, str, str], None]) -> None:
    ents = net.entities
    rels = list(net.relationships.values())
    officers = [r for r in rels if r.type == RelationType.OFFICER]
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731

    # 1. Formation agents and corporate directors
    for e in ents.values():
        if e.type != EntityType.COMPANY:
            continue
        n = _norm(e.name)
        agent = next((a for a in FORMATION_AGENTS if a in n), None)
        served = sorted(
            {
                name(r.target_id)
                for r in rels
                if r.source_id == e.id and r.type == RelationType.OFFICER
            }
        )
        if agent and served:
            flag(
                "formation_agent",
                e.id,
                f"{e.name} (corporate service provider recurring in offshore leaks) acts for "
                f"{', '.join(served[:4])}{'…' if len(served) > 4 else ''}",
            )
        roles = [
            r
            for r in officers
            if r.source_id == e.id and CORPORATE_OFFICER_ROLES.search(r.role or "director")
        ]
        if roles and not agent:
            for r in roles[:3]:
                flag(
                    "corporate_director",
                    r.target_id,
                    f"{e.name} (a company) is {(r.role or 'officer').lower()} of {name(r.target_id)}",
                )

    # 2. Mandates across many jurisdictions (same person, several registers)
    min_countries = int(t.get("multi_jurisdiction_min_countries", 3))
    for e in ents.values():
        if e.type != EntityType.PERSON:
            continue
        countries = {
            ents[r.target_id].jurisdiction
            for r in rels
            if r.source_id == e.id
            and r.type
            in (RelationType.OFFICER, RelationType.SHAREHOLDER, RelationType.BENEFICIAL_OWNER)
            and r.target_id in ents
            and ents[r.target_id].jurisdiction
        }
        if len(countries) >= min_countries:
            flag(
                "multi_jurisdiction_officer",
                e.id,
                f"{e.name} holds positions in companies of {len(countries)} countries: "
                + ", ".join(sorted(c for c in countries if c)),
            )

    # 3. Possibly the same person in two registries (not merged: no date of birth to confirm)
    persons = [e for e in ents.values() if e.type == EntityType.PERSON]
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(persons):
        for b in persons[i + 1 :]:
            if a.birth_date and b.birth_date and a.birth_date[:7] != b.birth_date[:7]:
                continue
            src_a = {s.source for s in a.sources}
            src_b = {s.source for s in b.sources}
            if src_a & src_b:
                continue  # same register: two different records are two people
            score = fuzz.token_set_ratio(_norm(a.name), _norm(b.name))
            if score >= 92 and (a.id, b.id) not in seen:
                seen.add((a.id, b.id))
                flag(
                    "possible_same_person",
                    a.id,
                    f"{a.name} and {b.name} ({score:.0f}% name match, found in different registers) "
                    "may be the same person: compare dates of birth and addresses",
                )

    # 4. Companies incorporated in a batch (same day / week) with a shared officer or address
    window = int(t.get("batch_incorporation_days", 7))
    companies = [e for e in ents.values() if e.type == EntityType.COMPANY and e.incorporation_date]
    links: dict[str, set[str]] = defaultdict(set)
    for r in rels:
        if r.type in (RelationType.OFFICER, RelationType.REGISTERED_AT, RelationType.SHAREHOLDER):
            other = r.source_id if r.type != RelationType.REGISTERED_AT else r.target_id
            company = r.target_id if r.type != RelationType.REGISTERED_AT else r.source_id
            links[company].add(other)
    reported: set[frozenset[str]] = set()
    for i, a in enumerate(companies):
        batch = [a]
        for b in companies[i + 1 :]:
            try:
                gap = abs(
                    (
                        date.fromisoformat(str(a.incorporation_date))
                        - date.fromisoformat(str(b.incorporation_date))
                    ).days
                )
            except ValueError:
                continue
            if gap <= window and links[a.id] & links[b.id]:
                batch.append(b)
        key = frozenset(c.id for c in batch)
        if len(batch) >= 2 and key not in reported and not any(key <= k for k in reported):
            reported.add(key)
            shared = set.intersection(*(links[c.id] for c in batch))
            flag(
                "batch_incorporation",
                a.id,
                f"{', '.join(c.name for c in batch[:4])} were incorporated within {window} days "
                f"({', '.join(sorted({str(c.incorporation_date) for c in batch}))}) and share "
                f"{', '.join(name(x) for x in list(shared)[:2])}",
            )

    # 5. Officer resigning shortly before a liquidation / insolvency
    before = int(t.get("pre_event_resignation_days", 180))
    for r in officers:
        if not r.end_date or r.target_id not in ents:
            continue
        company = ents[r.target_id]
        events: list[tuple[date, str]] = []
        if company.status == CompanyStatus.DISSOLVED and company.dissolution_date:
            events.append((date.fromisoformat(str(company.dissolution_date)), "dissolution"))
        for d in company.documents:
            if "insolvency" in d.flags and d.date:
                events.append((date.fromisoformat(str(d.date)), "insolvency proceedings"))
        try:
            left = date.fromisoformat(str(r.end_date))
        except ValueError:
            continue
        for when, what in sorted(events):  # the first event after the departure
            gap = (when - left).days
            if 1 <= gap <= before:  # same day = the mandate ended with the company
                flag(
                    "pre_event_resignation",
                    r.source_id,
                    f"{name(r.source_id)} left {company.name} on {left}, {gap} days before its {what} ({when})",
                )
                break

    # 6. High officer turnover
    turnover = int(t.get("officer_turnover_changes", 4))
    by_company: dict[str, list[date]] = defaultdict(list)
    for r in officers:
        for d in (r.start_date, r.end_date):
            if d:
                with contextlib.suppress(ValueError):
                    by_company[r.target_id].append(date.fromisoformat(str(d)))
    for cid, days in by_company.items():
        days.sort()
        for i in range(len(days)):
            j = i
            while j + 1 < len(days) and (days[j + 1] - days[i]).days <= 365:
                j += 1
            if j - i + 1 >= turnover:
                flag(
                    "officer_turnover",
                    cid,
                    f"{name(cid)}: {j - i + 1} officer appointments / departures between {days[i]} and {days[j]}",
                )
                break

    # 7. Beneficial owners declared as public officials in a register (e.g. Slovak RPVS)
    for e in ents.values():
        if e.type == EntityType.PERSON and e.extra.get("public_official"):
            flag(
                "pep_match",
                e.id,
                f"{e.name} is declared a public official in a beneficial-ownership register",
            )
