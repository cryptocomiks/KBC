from datetime import date

from app.connectors.demo import DemoFrRegistry, DemoIntlRegistry, DemoSanctions, resolve_date
from app.models import ListType, RelationType
from app.settings import Settings


def test_relative_dates():
    assert resolve_date("@-10m", date(2026, 9, 24)) == "2025-11-24"
    assert resolve_date("2020-01-01") == "2020-01-01"


def test_demo_connectors_disabled_outside_demo_mode():
    conn = DemoFrRegistry(Settings(demo_mode=False))
    enabled, message = conn.status()
    assert not enabled and "DEMO_MODE" in message


def test_common_interface_and_provenance(registry):
    fr = registry.connectors["demo_fr_registry"]
    people = fr.search_person("Mohamed Qadrany")
    assert people[0].name == "Mohammed Qadrany"
    prov = people[0].sources[0]
    assert prov.source == "demo_fr_registry" and prov.url.startswith("https://example.org/")
    assert prov.retrieved_at is not None

    company = fr.get_company_details("demo_fr_registry:900100101")
    assert company.registration_number == "900100101"
    officers = fr.get_officers(company.id)
    assert {o.entity.name for o in officers} == {"Mohammed Qadrany", "Sofia Marchetti"}
    holders = fr.get_shareholders(company.id)
    assert {h.relationship.type for h in holders} == {
        RelationType.SHAREHOLDER,
        RelationType.BENEFICIAL_OWNER,
    }


def test_domiciliation_search():
    intl = DemoIntlRegistry()
    assert len(intl.search_address("7 rue des Hêtres-Blancs, L-1835 Luxembourg")) == 6


def test_screening_returns_explained_hits():
    intl, sanctions = DemoIntlRegistry(), DemoSanctions()
    terekhov = intl.get_person_details("demo_intl_registry:OP-1004")
    hits = sanctions.screen(terekhov)
    assert hits and hits[0].list_type == ListType.SANCTION and hits[0].score >= 95
    assert any("date of birth" in e for e in hits[0].explanation)


def test_screening_weak_hit_for_namesake_with_other_dob():
    fr, sanctions = DemoFrRegistry(), DemoSanctions()
    hits = sanctions.screen(fr.get_person_details("demo_fr_registry:P-001"))
    assert hits and all(h.score < 70 for h in hits)
