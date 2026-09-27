"""Beneficial ownership analysis: effective interests, coverage, SMO fallback, 50 % rule."""

from app.beneficial import analyse, blocked_by_ownership
from app.graph.expander import Network
from app.models import (
    Entity,
    EntityType,
    ListType,
    Provenance,
    Relationship,
    RelationType,
    ScreeningHit,
)
from app.risk.engine import RiskEngine


def prov():
    return Provenance(source="t", source_label="test")


def company(eid, name, jur="FR", offshore=False):
    return Entity(
        id=eid, type=EntityType.COMPANY, name=name, jurisdiction=jur, is_offshore=offshore
    )


def person(eid, name):
    return Entity(id=eid, type=EntityType.PERSON, name=name)


def own(src, dst, pct, kind=RelationType.SHAREHOLDER):
    return Relationship(
        id=f"{kind.value}:{src}>{dst}",
        type=kind,
        source_id=src,
        target_id=dst,
        share_pct=pct,
        sources=[prov()],
    )


def officer(src, dst, role):
    return Relationship(
        id=f"off:{src}>{dst}",
        type=RelationType.OFFICER,
        source_id=src,
        target_id=dst,
        role=role,
        sources=[prov()],
    )


def sanction(eid):
    return ScreeningHit(
        entity_id=eid,
        list_type=ListType.SANCTION,
        dataset="OFAC",
        matched_name="x",
        score=100,
        provenance=prov(),
    )


def network(entities, rels, hits=(), max_depth=3, depth=None):
    return Network(
        subject_id="S",
        max_depth=max_depth,
        max_nodes=50,
        entities={e.id: e for e in entities},
        relationships={r.id: r for r in rels},
        depth=depth or {e.id: 1 for e in entities} | {"S": 0},
        hits=list(hits),
    )


def test_effective_interest_is_summed_over_routes_and_undeclared_owner_is_found():
    # A holds 60 % of H1 (which holds 50 % of S) and 20 % of S directly: 30 + 20 = 50 %.
    ents = [
        company("S", "Subject SA"),
        company("H1", "Holding One", "LU"),
        person("A", "Alice"),
        person("B", "Bob"),
    ]
    rels = [
        own("H1", "S", 50),
        own("A", "H1", 60),
        own("A", "S", 20),
        own("B", "S", 30),
        own("B", "S", 30, RelationType.BENEFICIAL_OWNER),
    ]
    a = analyse(network(ents, rels), "low")
    by = {o.name: o for o in a.owners}
    assert by["Alice"].effective_pct == 50 and len(by["Alice"].routes) == 2
    assert by["Alice"].status == "ubo_ownership" and not by["Alice"].declared
    assert by["Bob"].status == "ubo_both"
    assert a.traced_pct == 80 and a.unexplained_pct == 20
    cov = {c.name: c for c in a.coverage}
    assert cov["Holding One"].unexplained_pct == 40  # only 60 % of H1 identified
    assert any("Alice holds an effective 50 %" in q for q in a.questions)
    assert any("40 % of Holding One is not accounted for" in q for q in a.questions)


def test_enhanced_threshold_for_high_risk_and_smo_fallback():
    ents = [company("S", "Subject SA"), person("A", "Alice"), person("D", "Dan")]
    rels = [own("A", "S", 15), officer("D", "S", "Directeur général")]
    low = analyse(network(ents, rels), "medium")
    assert low.threshold_applied == 25 and low.owners[0].status == "below_threshold"
    assert [s["name"] for s in low.smo] == ["Dan"] and "senior managing official" in low.smo_reason
    high = analyse(network(ents, rels), "high")
    assert (
        high.threshold_applied == 10 and high.owners[0].status == "ubo_ownership" and not high.smo
    )


def test_dead_end_offshore_and_depth_limited_gap():
    ents = [company("S", "Subject SA"), company("V", "Island Holdings Ltd", "VG", offshore=True)]
    a = analyse(network(ents, [own("V", "S", 100)]), "low")
    row = next(c for c in a.coverage if c.name == "Island Holdings Ltd")
    assert row.dead_end and "offshore" in row.reason and not row.depth_limited
    assert any("Who owns Island Holdings Ltd" in q for q in a.questions)
    # The same company at the edge of the search: a deeper investigation, not a client question.
    limited = analyse(network(ents, [own("V", "S", 100)], max_depth=1), "low")
    assert limited.depth_limited and not any("Island Holdings" in q for q in limited.questions)


def test_ofac_50_percent_rule_aggregates_and_propagates():
    # X (sanctioned) 30 % + Y (sanctioned) 25 % of H: 55 % -> H blocked, and H's 60 % subsidiary S too.
    ents = [
        company("S", "Subject SA"),
        company("H", "Holdco"),
        person("X", "Xavier"),
        person("Y", "Yuri"),
        person("Z", "Zoe"),
    ]
    rels = [own("X", "H", 30), own("Y", "H", 25), own("H", "S", 60), officer("Z", "S", "Director")]
    net = network(ents, rels, [sanction("X"), sanction("Y")])
    rows = {r.name: r for r in blocked_by_ownership(net)}
    assert rows["Holdco"].blocked and rows["Holdco"].aggregate_pct == 55
    assert rows["Subject SA"].blocked and rows["Subject SA"].aggregate_pct == 60
    a = analyse(net, "critical")
    assert any("Freeze" in x and "Subject SA" in x for x in a.actions)
    assert not any(
        "sanction" in q.lower() or "Xavier" in q for q in a.questions
    )  # never told to the client
    factors = {f.key: f for f in RiskEngine().assess(net).factors}
    assert "sanctions_ownership" in factors and "Subject SA" in " ".join(
        factors["sanctions_ownership"].evidence
    )


def test_sanctioned_minority_owner_or_officer_is_flagged_as_control():
    ents = [company("S", "Subject SA"), person("X", "Xavier"), person("D", "Dmitri")]
    net = network(
        ents, [own("X", "S", 20), officer("D", "S", "Director")], [sanction("X"), sanction("D")]
    )
    [row] = blocked_by_ownership(net)
    assert not row.blocked and row.aggregate_pct == 20 and row.control == ["Dmitri"]
    assert "sanctions_minority_or_control" in {f.key for f in RiskEngine().assess(net).factors}


def test_person_subject_lists_holdings():
    ents = [person("S", "Sam"), company("C1", "One"), company("C2", "Two")]
    a = analyse(network(ents, [own("S", "C1", 80), own("C1", "C2", 50)]), "low")
    assert [(h["name"], h["effective_pct"], h["layers"]) for h in a.holdings] == [
        ("One", 80, 0),
        ("Two", 40, 1),
    ]
