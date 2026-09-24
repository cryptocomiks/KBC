"""EU/UK/CH watchlists, Wikidata (PEP, relatives, contacts), GDELT adverse media."""

import httpx
import respx

from app.connectors import open_datasets as od
from app.connectors.gdelt import GdeltConnector
from app.connectors.wikidata import WikidataConnector, WikidataPepConnector
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


def item(qid, label, description=None, **claims):
    """Minimal wbgetentities entity: claim values are item ids (Q...), strings or (value, qualifiers)."""

    def snak(v):
        if isinstance(v, str) and v.startswith("Q") and v[1:].isdigit():
            return {"datavalue": {"type": "wikibase-entityid", "value": {"id": v}}}
        if isinstance(v, str) and v.startswith("+"):
            return {"datavalue": {"type": "time", "value": {"time": v}}}
        return {"datavalue": {"type": "string", "value": v}}

    out = {"id": qid, "labels": {"en": {"value": label}}, "claims": {}}
    if description:
        out["descriptions"] = {"en": {"value": description}}
    for prop, values in claims.items():
        out["claims"][prop] = []
        for v in values if isinstance(values, list) else [values]:
            claim = {"mainsnak": snak(v[0] if isinstance(v, tuple) else v)}
            if isinstance(v, tuple):
                claim["qualifiers"] = {q: [snak(t)] for q, t in v[1].items()}
            out["claims"][prop].append(claim)
    return out


ENTITIES = {
    "Q1001": item(
        "Q1001",
        "Ana Minister",
        "Minister of Finance",
        P31="Q5",
        P569="+1970-02-03T00:00:00Z",
        P27="Q403",
        P39=[
            ("Q501", {"P580": "+2019-01-01T00:00:00Z"}),
            ("Q502", {"P580": "+2010-01-01T00:00:00Z", "P582": "+2018-12-31T00:00:00Z"}),
        ],
        P2002="anaminister",
        P968="mailto:ana@private.example",
        P856="https://ana.example",
        P26="Q1002",
        P1830="Q2002",
    ),
    "Q1002": item("Q1002", "Marko Minister", P31="Q5"),
    "Q2002": item(
        "Q2002",
        "Acme Group",
        "company",
        P31="Q4830453",
        P17="Q142",
        P856="https://acme.example",
        P968="mailto:contact@acme.example",
        P4264="acme-group",
        P1278="969500ABCDEF12345678",
    ),
    "Q403": item("Q403", "Serbia", P297="RS"),
    "Q142": item("Q142", "France", P297="FR"),
    "Q501": item("Q501", "Minister of Finance"),
    "Q502": item("Q502", "Member of Parliament"),
}


def api_reply(request):
    params = request.url.params
    if params["action"] == "wbgetentities":
        ids = params["ids"].split("|")
        return httpx.Response(
            200, json={"entities": {i: ENTITIES[i] for i in ids if i in ENTITIES}}
        )
    term = params["search"]
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
    respx.get("https://www.wikidata.org/w/api.php").mock(side_effect=api_reply)
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


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Acme Group fined for bribery - Example Times</title><link>https://news.example/b</link>
<pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate><source url="https://news.example">Example Times</source></item>
</channel></rss>"""


@respx.mock
def test_gdelt_rate_limited_falls_back_to_google_news():
    gdelt = respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(429, text="Please limit requests to one every 5 seconds")
    )
    respx.get("https://news.google.com/rss/search").mock(return_value=httpx.Response(200, text=RSS))
    [doc] = GdeltConnector(LIVE).get_documents(
        Entity(id="c", type=EntityType.COMPANY, name="Acme Group")
    )
    assert gdelt.call_count == 1  # never retried: GDELT asks clients not to
    assert doc.url == "https://news.example/b" and doc.date.isoformat() == "2026-08-03"
    assert "Google News" in doc.source and doc.flags == ["adverse_media"]


def test_demo_pep_relative_is_flagged(registry):
    seed = registry.connectors["demo_intl_registry"].get_company_details(
        "demo_intl_registry:gb/15873344"
    )
    net = NetworkExpander(registry, max_depth=2, max_nodes=80).expand([seed])
    rel = [r for r in net.relationships.values() if r.type == RelationType.RELATIVE]
    assert rel, "spouse link expected"
    factors = {f.key: f for f in RiskEngine().assess(net).factors}
    assert "pep_relative" in factors and "Mirela" in factors["pep_relative"].evidence[0]


def test_year_only_dates_never_break_a_search():
    e = Entity(
        id="x",
        type=EntityType.COMPANY,
        name="Acme",
        incorporation_date="2000",
        dissolution_date="2010-05",
    )
    assert e.incorporation_date is None and e.dissolution_date is None
    from app.connectors.wikidata import _full

    assert _full("2000") is None and _full("2000-03-01") == "2000-03-01"


def test_wikidata_company_ranking_prefers_the_corporate_entity():
    from app.connectors.wikidata import _corporate_weight

    team = {"description": "French cycling team", "lei": None, "links": 1}
    group = {"description": "French multinational energy company", "lei": "LEI1", "links": 4}
    assert _corporate_weight(group) > _corporate_weight(team)
