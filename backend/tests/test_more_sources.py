"""EU/UK/CH watchlists, Wikidata (PEP, relatives, contacts), GDELT adverse media."""

import httpx
import respx

from app.connectors import open_datasets as od
from app.connectors.gdelt import GdeltConnector
from app.connectors.wikidata import SPARQL, WikidataConnector, WikidataPepConnector
from app.graph.expander import NetworkExpander
from app.models import Entity, EntityType, ListType, RelationType
from app.risk.engine import RiskEngine
from app.settings import Settings

LIVE = Settings(live_sources=True, open_datasets="eu_fsf,interpol_red_notices")

EU_CSV = """id,schema,name,aliases,birth_date,countries,addresses,identifiers,sanctions,phones,emails,dataset,first_seen,last_seen,last_change
NK-1,Person,Ivan Petrov,Иван Петров;I. Petrov,1960-01-01,ru,,,EU Regulation 269/2014,,,EU FSF,2022-03-01,2026-09-01,2026-09-01
NK-2,Company,Acme Arms JSC,,,ru,,,EU Regulation 833/2014,,,EU FSF,2022-03-01,2026-09-01,2026-09-01
V-1,Vessel,SHIP ONE,,,,,,,,,EU FSF,2022-03-01,2026-09-01,2026-09-01
"""
INTERPOL_CSV = """id,schema,name,aliases,birth_date,countries,addresses,identifiers,sanctions,phones,emails,dataset,first_seen,last_seen,last_change
IP-1,Person,John Wanted,,1980-05-05,fr,,,,,,Interpol,2024-01-01,2026-09-01,2026-09-01
"""


def person(name, dob=None, nat=()):
    return Entity(
        id=f"x:{name}", type=EntityType.PERSON, name=name, birth_date=dob, nationalities=list(nat)
    )


@respx.mock
def test_open_watchlists_index_and_classify(monkeypatch):
    monkeypatch.setattr(od, "_STATE", od._State())
    respx.get(od.URL.format(dataset="eu_fsf")).mock(return_value=httpx.Response(200, text=EU_CSV))
    respx.get(od.URL.format(dataset="interpol_red_notices")).mock(
        return_value=httpx.Response(200, text=INTERPOL_CSV)
    )
    conn = od.OpenDatasetsConnector(LIVE)
    [hit] = conn.screen(person("Ivan Petrov", "1960-01-01", ["RU"]))
    assert hit.list_type == ListType.SANCTION and hit.dataset.startswith("EU") and hit.score >= 95
    assert hit.provenance.url == "https://www.opensanctions.org/entities/NK-1/"
    [wanted] = conn.screen(person("John Wanted", "1980-05-05"))
    assert wanted.list_type == ListType.ADVERSE and "Interpol" in wanted.dataset
    assert (
        conn.screen(Entity(id="c", type=EntityType.COMPANY, name="ACME ARMS"))[0].matched_name
        == "Acme Arms JSC"
    )
    assert (
        conn.screen(Entity(id="v", type=EntityType.COMPANY, name="Ship One")) == []
    )  # vessels skipped


def binding(**kw):
    return {k: {"type": "literal", "value": v} for k, v in kw.items()}


def sparql_reply(request):
    query = request.url.params["query"]
    if "GROUP_CONCAT" in query:  # details
        rows = []
        if "Q1001" in query:
            rows.append(
                binding(
                    item="http://www.wikidata.org/entity/Q1001",
                    itemLabel="Ana Minister",
                    itemDescription="Minister of Finance",
                    birth="1970-02-03T00:00:00Z",
                    countries="RS",
                    types="Q5",
                    positions="Minister of Finance|2019-01-01T00:00:00Z|;;Member of Parliament|2010-01-01T00:00:00Z|2018-12-31T00:00:00Z",
                    twitter="anaminister",
                    email="mailto:ana@private.example",
                    website="https://ana.example",
                )
            )
        if "Q2002" in query:
            rows.append(
                binding(
                    item="http://www.wikidata.org/entity/Q2002",
                    itemLabel="Acme Group",
                    itemDescription="company",
                    countries="FR",
                    types="Q4830453",
                    website="https://acme.example",
                    email="mailto:contact@acme.example",
                    linkedin_org="acme-group",
                    leiCode="969500ABCDEF12345678",
                )
            )
        return httpx.Response(200, json={"results": {"bindings": rows}})
    return httpx.Response(
        200,
        json={
            "results": {
                "bindings": [
                    binding(
                        item="http://www.wikidata.org/entity/Q1001",
                        prop="http://www.wikidata.org/prop/direct/P26",
                        other="http://www.wikidata.org/entity/Q1002",
                        otherLabel="Marko Minister",
                        isHuman="true",
                    ),
                    binding(
                        item="http://www.wikidata.org/entity/Q1001",
                        prop="http://www.wikidata.org/prop/direct/P1830",
                        other="http://www.wikidata.org/entity/Q2002",
                        otherLabel="Acme Group",
                        isHuman="false",
                    ),
                ]
            }
        },
    )


def search_reply(request):
    term = request.url.params["search"]
    if "Ana" in term:
        return httpx.Response(
            200,
            json={"search": [{"id": "Q1001", "label": "Ana Minister", "description": "Minister"}]},
        )
    if "Acme" in term:
        return httpx.Response(
            200,
            json={
                "search": [
                    {"id": "Q2002", "label": "Acme Group", "description": "company"},
                    {"id": "Q9", "label": "Acme", "description": "family name"},
                ]
            },
        )
    return httpx.Response(200, json={"search": []})


@respx.mock
def test_wikidata_pep_relatives_and_contacts():
    respx.get("https://www.wikidata.org/w/api.php").mock(side_effect=search_reply)
    respx.get(SPARQL).mock(side_effect=sparql_reply)
    wd = WikidataConnector(LIVE)

    [ana] = wd.search_person("Ana Minister")
    assert (
        ana.birth_date == "1970-02-03"
        and "Minister of Finance (2019–)" in ana.extra["positions_held"]
    )
    roles = {(link.relationship.type, link.entity.name) for link in wd.get_person_roles(ana.id)}
    assert roles == {
        (RelationType.RELATIVE, "Marko Minister"),
        (RelationType.SHAREHOLDER, "Acme Group"),
    }

    [acme] = wd.search_company("Acme")  # the "family name" item is filtered out
    assert acme.jurisdiction == "FR" and acme.identifiers["LEI"] == "969500ABCDEF12345678"
    docs = {d.title: d for d in wd.get_documents(acme)}
    assert docs["Published e-mail"].url == "mailto:contact@acme.example"
    assert docs["LinkedIn page"].url == "https://www.linkedin.com/company/acme-group"

    person_docs = {d.title for d in wd.get_documents(ana)}
    assert "X / Twitter @anaminister" in person_docs
    assert "Published e-mail" not in person_docs  # never a person's e-mail, even when published

    [hit] = WikidataPepConnector(LIVE).screen_many([person("Ana Minister", "1970-02-03")])
    assert (
        hit.list_type == ListType.PEP
        and hit.score >= 95
        and "Minister of Finance" in hit.details["positions"]
    )


@respx.mock
def test_gdelt_adverse_media_documents():
    respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://news.example/a",
                        "title": "Acme Group probed for money laundering",
                        "seendate": "20260801T101500Z",
                        "domain": "news.example",
                        "language": "English",
                        "sourcecountry": "France",
                    }
                ]
            },
        )
    )
    [doc] = GdeltConnector(LIVE).get_documents(
        Entity(id="c", type=EntityType.COMPANY, name="Acme Group")
    )
    assert (
        doc.kind == "adverse_media"
        and doc.flags == ["adverse_media"]
        and doc.date.isoformat() == "2026-08-01"
    )


@respx.mock
def test_gdelt_non_json_answer_is_ignored():
    respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(200, text="Please limit requests")
    )
    assert (
        GdeltConnector(LIVE).get_documents(
            Entity(id="c", type=EntityType.COMPANY, name="Acme Group")
        )
        == []
    )


def test_demo_pep_relative_is_flagged(registry):
    seed = registry.connectors["demo_intl_registry"].get_company_details(
        "demo_intl_registry:gb/15873344"
    )
    net = NetworkExpander(registry, max_depth=2, max_nodes=80).expand([seed])
    rel = [r for r in net.relationships.values() if r.type == RelationType.RELATIVE]
    assert rel, "spouse link expected"
    factors = {f.key: f for f in RiskEngine().assess(net).factors}
    assert "pep_relative" in factors and "Mirela" in factors["pep_relative"].evidence[0]
