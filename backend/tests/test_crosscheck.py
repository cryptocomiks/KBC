from datetime import date

from app.graph.expander import Network
from app.models import (
    CompanyStatus,
    Document,
    Entity,
    EntityType,
    Provenance,
    Relationship,
    RelationType,
)
from app.risk.crosscheck import cross_checks

T = {
    "multi_jurisdiction_min_countries": 3,
    "batch_incorporation_days": 7,
    "pre_event_resignation_days": 180,
    "officer_turnover_changes": 4,
}


def src(name):
    return [Provenance(source=name, source_label=name)]


def person(pid, name, source="reg_a", dob=None):
    return Entity(id=pid, type=EntityType.PERSON, name=name, birth_date=dob, sources=src(source))


def company(cid, name, jur="LU", **kw):
    return Entity(
        id=cid, type=EntityType.COMPANY, name=name, jurisdiction=jur, sources=src("reg_a"), **kw
    )


def officer(i, who, of, role="Director", start=None, end=None):
    return Relationship(
        id=f"r{i}",
        type=RelationType.OFFICER,
        source_id=who,
        target_id=of,
        role=role,
        start_date=start,
        end_date=end,
    )


def run(entities, rels):
    net = Network(
        subject_id=entities[0].id,
        max_depth=3,
        max_nodes=50,
        entities={e.id: e for e in entities},
        relationships={r.id: r for r in rels},
        depth={e.id: 1 for e in entities},
    )
    found: dict[str, list[str]] = {}
    cross_checks(net, T, lambda k, eid, ev: found.setdefault(k, []).append(ev))
    return found


def test_formation_agent_and_corporate_director():
    found = run(
        [
            company("A", "Alpha Ltd", "VG"),
            company("M", "Mossack Fonseca & Co. (BVI) Ltd", "VG"),
            company("N", "Northwind Nominees Ltd", "GB"),
        ],
        [officer(1, "M", "A", "Registered agent"), officer(2, "N", "A", "Director")],
    )
    assert "Alpha Ltd" in found["formation_agent"][0]
    assert found["corporate_director"] == [
        "Northwind Nominees Ltd (a company) is director of Alpha Ltd"
    ]


def test_positions_in_many_countries_and_possible_same_person():
    found = run(
        [
            person("P", "Jean Dupont"),
            person("Q", "DUPONT Jean", source="reg_b"),
            company("A", "A SA", "LU"),
            company("B", "B AG", "CH"),
            company("C", "C Ltd", "CY"),
        ],
        [officer(1, "P", "A"), officer(2, "P", "B"), officer(3, "P", "C")],
    )
    assert "3 countries: CH, CY, LU" in found["multi_jurisdiction_officer"][0]
    assert "may be the same person" in found["possible_same_person"][0]


def test_same_register_or_different_birth_dates_are_not_the_same_person():
    found = run(
        [
            person("P", "Jean Dupont", dob="1960-01-01"),
            person("Q", "Jean Dupont", source="reg_b", dob="1985-05-05"),
            person("R", "Jean Dupont"),
        ],
        [],
    )
    assert "possible_same_person" not in found or all(
        "R" not in e for e in found["possible_same_person"]
    )
    assert not any("1985" in e for e in found.get("possible_same_person", []))


def test_batch_incorporation_needs_a_shared_party():
    found = run(
        [
            person("P", "Anna Berg"),
            company("A", "One Sarl", incorporation_date=date(2024, 3, 1)),
            company("B", "Two Sarl", incorporation_date=date(2024, 3, 4)),
            company("C", "Three Sarl", incorporation_date=date(2024, 3, 2)),  # no shared party
        ],
        [officer(1, "P", "A"), officer(2, "P", "B")],
    )
    [ev] = found["batch_incorporation"]
    assert "One Sarl, Two Sarl" in ev and "Anna Berg" in ev and "Three" not in ev


def test_resignation_before_insolvency_but_not_on_the_dissolution_day():
    liquidated = company(
        "A",
        "Failing Sarl",
        status=CompanyStatus.DISSOLVED,
        dissolution_date=date(2023, 6, 30),
        documents=[
            Document(
                title="Liquidation",
                kind="legal_notice",
                date=date(2023, 3, 1),
                source="BODACC",
                flags=["insolvency"],
            )
        ],
    )
    found = run(
        [person("P", "Early Leaver"), person("Q", "Last Manager"), liquidated],
        [officer(1, "P", "A", end=date(2023, 1, 15)), officer(2, "Q", "A", end=date(2023, 6, 30))],
    )
    [ev] = found["pre_event_resignation"]
    assert ev.startswith(
        "Early Leaver left Failing Sarl on 2023-01-15, 45 days before its insolvency"
    )


def test_officer_turnover():
    found = run(
        [company("A", "Revolving Door SA"), *[person(f"P{i}", f"Person {i}") for i in range(3)]],
        [
            officer(1, "P0", "A", start=date(2024, 1, 1), end=date(2024, 3, 1)),
            officer(2, "P1", "A", start=date(2024, 3, 1), end=date(2024, 8, 1)),
            officer(3, "P2", "A", start=date(2024, 8, 1)),
        ],
    )
    assert "Revolving Door SA: 5 officer appointments" in found["officer_turnover"][0]
