from app.graph.ownership import (
    corporate_layers_above,
    find_cycles,
    indirect_stakes,
    ownership_graph,
)
from app.models import Entity, EntityType, Relationship, RelationType


def sh(src, tgt, pct, end=None):
    return Relationship(
        id=f"{src}{tgt}",
        type=RelationType.SHAREHOLDER,
        source_id=src,
        target_id=tgt,
        share_pct=pct,
        end_date=end,
    )


def test_indirect_stakes_multiply_along_paths_and_cut_cycles():
    g = ownership_graph(
        [sh("P", "A", 60), sh("A", "B", 51), sh("B", "C", 30), sh("C", "D", 100), sh("D", "B", 49)]
    )
    stakes = indirect_stakes(g, "P")
    assert stakes["A"] == 60
    assert stakes["B"] == 30.6
    assert stakes["C"] == 9.18
    assert stakes["D"] == 9.18


def test_cycles_detected():
    g = ownership_graph([sh("B", "C", 30), sh("C", "D", 100), sh("D", "B", 49)])
    cycles = find_cycles(g)
    assert len(cycles) == 1 and set(cycles[0]) == {"B", "C", "D"}


def test_ended_holdings_ignored():
    g = ownership_graph([sh("P", "A", 100, end="2020-01-01")])
    assert indirect_stakes(g, "P") == {}


def test_corporate_layers_only_count_companies():
    ents = {k: Entity(id=k, type=EntityType.COMPANY, name=k) for k in "ABCD"}
    ents["P"] = Entity(id="P", type=EntityType.PERSON, name="P")
    g = ownership_graph(
        [sh("P", "A", 100), sh("A", "B", 100), sh("B", "C", 100), sh("C", "D", 100)]
    )
    assert corporate_layers_above(g, "D", ents) == ["C", "B", "A"]
