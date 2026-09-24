from datetime import date

import pytest

from app.graph.expander import Network, NetworkExpander
from app.models import (
    CompanyStatus,
    Entity,
    EntityType,
    ListType,
    Provenance,
    Relationship,
    RelationType,
    ScreeningHit,
)
from app.risk.config import JurisdictionLists, RiskConfig
from app.risk.engine import RiskEngine

CFG = RiskConfig(
    weights={
        "sanctions_match": 40,
        "pep_match": 20,
        "pep_possible_match": 5,
        "offshore_jurisdiction": 10,
        "circular_ownership": 15,
        "dissolved_company": 3,
        "recent_incorporation": 4,
        "missing_accounts": 5,
        "shared_domiciliation": 6,
        "fatf_greylist": 10,
    },
    proximity_multiplier={"0": 1.0, "1": 0.5, "default": 0.25},
    thresholds={
        "strong_match_score": 85,
        "possible_match_score": 70,
        "long_chain_min_layers": 3,
        "shared_address_min_companies": 3,
        "recent_incorporation_months": 18,
        "accounts_overdue_months": 18,
        "nominee_min_mandates": 4,
    },
    levels={"low": 0, "medium": 20, "high": 45, "critical": 70},
)
JUR = JurisdictionLists(offshore_centres={"VG"}, fatf_greylist={"VG"})
TODAY = date(2026, 9, 1)


def prov():
    return Provenance(source="t", source_label="test")


def hit(eid, list_type, score):
    return ScreeningHit(
        entity_id=eid,
        list_type=list_type,
        dataset="d",
        matched_name="x",
        score=score,
        provenance=prov(),
    )


def net(entities, depth, rels=(), hits=()):
    return Network(
        subject_id="S",
        max_depth=3,
        max_nodes=50,
        entities={e.id: e for e in entities},
        relationships={r.id: r for r in rels},
        depth=depth,
        hits=list(hits),
    )


def test_score_is_sum_of_weighted_factors():
    s = Entity(id="S", type=EntityType.PERSON, name="Subject")
    c = Entity(
        id="C",
        type=EntityType.COMPANY,
        name="Offshore Co",
        jurisdiction="VG",
        incorporation_date=date(2010, 1, 1),
        last_accounts_date=date(2026, 1, 1),
    )
    result = RiskEngine(CFG, JUR, TODAY).assess(
        net([s, c], {"S": 0, "C": 1}, hits=[hit("S", ListType.PEP, 97)])
    )
    points = {f.key: f.points for f in result.factors}
    assert points == {"pep_match": 20.0, "offshore_jurisdiction": 5.0, "fatf_greylist": 5.0}
    assert result.score == 30.0
    assert result.level == "medium"
    assert result.entity_levels["S"] == "medium"


def test_factor_counted_once_whatever_the_volume():
    s = Entity(id="S", type=EntityType.PERSON, name="S")
    companies = [
        Entity(id=f"C{i}", type=EntityType.COMPANY, name=f"C{i}", status=CompanyStatus.DISSOLVED)
        for i in range(5)
    ]
    result = RiskEngine(CFG, JUR, TODAY).assess(
        net([s, *companies], {"S": 0, **{c.id: 1 for c in companies}})
    )
    [factor] = result.factors
    assert factor.key == "dissolved_company" and factor.points == 1.5 and len(factor.entities) == 5


def test_hit_thresholds():
    s = Entity(id="S", type=EntityType.PERSON, name="S")
    weak = RiskEngine(CFG, JUR, TODAY).assess(
        net([s], {"S": 0}, hits=[hit("S", ListType.SANCTION, 60)])
    )
    possible = RiskEngine(CFG, JUR, TODAY).assess(
        net([s], {"S": 0}, hits=[hit("S", ListType.PEP, 75)])
    )
    assert weak.score == 0 and not weak.factors
    assert [f.key for f in possible.factors] == ["pep_possible_match"]


def test_circular_ownership_and_shared_address():
    ents = [Entity(id="S", type=EntityType.PERSON, name="S")]
    ents += [
        Entity(
            id=x,
            type=EntityType.COMPANY,
            name=x,
            incorporation_date=date(2000, 1, 1),
            last_accounts_date=date(2026, 1, 1),
        )
        for x in "ABC"
    ]
    ents.append(
        Entity(
            id="addr", type=EntityType.ADDRESS, name="1 Main St", extra={"companies_registered": 12}
        )
    )
    rels = [
        Relationship(
            id=f"{a}{b}", type=RelationType.SHAREHOLDER, source_id=a, target_id=b, share_pct=50
        )
        for a, b in [("A", "B"), ("B", "C"), ("C", "A")]
    ]
    result = RiskEngine(CFG, JUR, TODAY).assess(
        net(ents, {"S": 0, "A": 1, "B": 1, "C": 1, "addr": 2}, rels)
    )
    keys = {f.key for f in result.factors}
    assert keys == {"circular_ownership", "shared_domiciliation"}
    assert result.cycles


def test_score_capped_at_100():
    s = Entity(id="S", type=EntityType.PERSON, name="S")
    cfg = CFG.model_copy(update={"weights": {**CFG.weights, "sanctions_match": 150}})
    result = RiskEngine(cfg, JUR, TODAY).assess(
        net([s], {"S": 0}, hits=[hit("S", ListType.SANCTION, 99)])
    )
    assert result.score == 100


@pytest.mark.parametrize("depth,expected_level", [(1, "low"), (3, "critical")])
def test_demo_scenario_risk_grows_with_depth(registry, depth, expected_level):
    seed = registry.connectors["demo_fr_registry"].get_person_details("demo_fr_registry:P-001")
    network = NetworkExpander(registry, max_depth=depth, max_nodes=100).expand([seed])
    result = RiskEngine().assess(network)
    assert result.level == expected_level
    for f in result.factors:
        assert f.evidence and f.points == round(f.weight * f.multiplier, 1)


def test_undeclared_ubo_detected():
    ents = [
        Entity(
            id="S",
            type=EntityType.COMPANY,
            name="Target",
            incorporation_date=date(2000, 1, 1),
            last_accounts_date=date(2026, 1, 1),
        ),
        Entity(
            id="H",
            type=EntityType.COMPANY,
            name="Holding",
            incorporation_date=date(2000, 1, 1),
            last_accounts_date=date(2026, 1, 1),
        ),
        Entity(id="A", type=EntityType.PERSON, name="Declared"),
        Entity(id="B", type=EntityType.PERSON, name="Hidden"),
    ]
    rels = [
        Relationship(
            id="1", type=RelationType.SHAREHOLDER, source_id="A", target_id="S", share_pct=40
        ),
        Relationship(
            id="2", type=RelationType.SHAREHOLDER, source_id="H", target_id="S", share_pct=60
        ),
        Relationship(
            id="3", type=RelationType.SHAREHOLDER, source_id="B", target_id="H", share_pct=50
        ),
        Relationship(
            id="4", type=RelationType.BENEFICIAL_OWNER, source_id="A", target_id="S", share_pct=40
        ),
    ]
    cfg = CFG.model_copy(update={"weights": {**CFG.weights, "ubo_discrepancy": 12}})
    result = RiskEngine(cfg, JUR, TODAY).assess(net(ents, {"S": 0, "H": 1, "A": 1, "B": 2}, rels))
    [factor] = [f for f in result.factors if f.key == "ubo_discrepancy"]
    assert factor.points == 12 and "Hidden holds an effective 30%" in factor.evidence[0]
