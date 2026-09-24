from app.graph.expander import NetworkExpander
from app.models import EntityType, RelationType

SUBJECT = "demo_fr_registry:P-001"


def seed(registry):
    return registry.connectors["demo_fr_registry"].get_person_details(SUBJECT)


def names(net):
    return {e.name for e in net.entities.values()}


def test_depth_controls_expansion(registry):
    n1 = NetworkExpander(registry, max_depth=1, max_nodes=100).expand([seed(registry)])
    n3 = NetworkExpander(registry, max_depth=3, max_nodes=100).expand([seed(registry)])
    assert max(n1.depth.values()) == 1
    assert "Ruslan Terekhov" not in names(n1)
    assert "Ruslan Terekhov" in names(n3)
    assert len(n3.entities) > len(n1.entities)


def test_node_limit_truncates(registry):
    net = NetworkExpander(registry, max_depth=3, max_nodes=10).expand([seed(registry)])
    assert len(net.entities) <= 10
    assert net.truncated and any("Node limit" in w for w in net.warnings)


def test_cross_source_deduplication(registry):
    net = NetworkExpander(registry, max_depth=2, max_nodes=100).expand([seed(registry)])
    subject = net.entities[net.subject_id]
    assert len(subject.record_ids) == 2  # FR registry + global registry
    meridian = [e for e in net.entities.values() if "Meridian Capital" in e.name]
    assert len(meridian) == 1 and len(meridian[0].sources) == 2
    assert net.merges


def test_frontier_edges_close_the_cycle(registry):
    # At depth 2 both Solenne (CY) and Northgate (BVI) are frontier nodes: the
    # edge between them must still be found to reveal the circular holding.
    net = NetworkExpander(registry, max_depth=2, max_nodes=100).expand([seed(registry)])
    by_name = {e.name: e.id for e in net.entities.values()}
    edges = {
        (r.source_id, r.target_id)
        for r in net.relationships.values()
        if r.type == RelationType.SHAREHOLDER
    }
    assert (by_name["Solenne Holdings Ltd"], by_name["Northgate Maritime Holdings Ltd"]) in edges


def test_offshore_flag_and_addresses(registry):
    net = NetworkExpander(registry, max_depth=2, max_nodes=100).expand([seed(registry)])
    northgate = next(e for e in net.entities.values() if e.name.startswith("Northgate"))
    assert northgate.is_offshore
    lux = next(
        e for e in net.entities.values() if e.type == EntityType.ADDRESS and "Hêtres" in e.name
    )
    assert lux.extra["companies_registered"] == 6


def test_every_query_is_logged(registry):
    net = NetworkExpander(registry, max_depth=1, max_nodes=100).expand([seed(registry)])
    assert net.queries and all(q.retrieved_at for q in net.queries)
    assert {q.source for q in net.queries} >= {
        "demo_fr_registry",
        "demo_intl_registry",
        "demo_sanctions",
    }
