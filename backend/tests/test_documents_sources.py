"""Court decisions, EU procurement, LittleSis and linked-website document sources."""

import json

import httpx
import pytest
import respx

from app.connectors.courts import CourtListenerConnector, SwissCourtsConnector
from app.connectors.littlesis import LittleSisConnector
from app.connectors.public_figures import is_public_figure, may_query
from app.connectors.ted import TedConnector
from app.connectors.websites import LinkedWebsitesConnector, registrable_domain
from app.models import Document, Entity, EntityType
from app.settings import Settings

LIVE = Settings(live_sources=True)


def company(name="Glencore Plc", website=None):
    extra = {"website": website} if website else {}
    return Entity(id=f"c:{name}", type=EntityType.COMPANY, name=name, extra=extra)


def person(name="Jonathan Goldberg", qid=None):
    ids = {"Wikidata": qid} if qid else {}
    return Entity(id=f"p:{name}", type=EntityType.PERSON, name=name, identifiers=ids)


# ------------------------------------------------------------------ privacy
def test_is_public_figure():
    assert is_public_figure(person(qid="Q42"))
    assert not is_public_figure(person())
    assert not is_public_figure(company())
    assert may_query(company()) and may_query(person(qid="Q42")) and not may_query(person())


@pytest.mark.parametrize(
    "conn_cls", [SwissCourtsConnector, CourtListenerConnector, LittleSisConnector, TedConnector]
)
def test_private_person_is_never_queried(conn_cls):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().mock(return_value=httpx.Response(500))
        assert conn_cls(LIVE).get_documents(person("Jane Private")) == []
        assert not route.called


# ------------------------------------------------------------------- courts
ENTSCHEIDSUCHE = {
    "took": 36,
    "hits": {
        "total": {"value": 2, "relation": "eq"},
        "hits": [
            {
                "_id": "GR_VG_001_U-2018-49_2021-12-14",
                "_source": {
                    "date": "2021-12-14",
                    "reference": ["U 2018 49"],
                    "attachment": {
                        "content_url": "https://entscheidsuche.ch/docs/GR_Gerichte/GR_VG_001_U-2018-49_2021-12-14.pdf"
                    },
                    "hierarchy": ["GR", "GR_VG", "GR_VG_001"],
                    "abstract": {
                        "de": "Staatshaftung",
                        "it": "Staatshaftung",
                        "fr": "Staatshaftung",
                    },
                    "title": {
                        "de": "Graubünden Verwaltungsgericht 1. Kammer 14.12.2021 U 2018 49",
                        "it": "Grigioni Tribunale amministrativo 1a Camera 14.12.2021 U 2018 49",
                        "fr": "Grisons Verwaltungsgericht 1. Kammer 14.12.2021 U 2018 49",
                    },
                },
            },
            {
                "_id": "GE_CJ_001_C-3570-2010_2013-11-22",
                "_source": {
                    "date": "2013-11-22",
                    "reference": ["C/3570/2010"],
                    "title": {"de": "Genf Cour de Justice 22.11.2013 C/3570/2010"},
                },
            },
        ],
    },
}


@respx.mock
def test_swiss_court_decisions():
    route = respx.post("https://entscheidsuche.ch/_search.php").mock(
        return_value=httpx.Response(
            200,
            content=json.dumps(ENTSCHEIDSUCHE).encode(),
            headers={"content-type": "application/x-javascript"},
        )
    )
    first, second = SwissCourtsConnector(LIVE).get_documents(company("Glencore"))
    body = json.loads(route.calls[0].request.content)
    assert body["query"]["simple_query_string"]["query"] == '"Glencore"' and body["size"] == 8
    assert first.title.startswith("Grisons") and first.summary == "Staatshaftung"
    assert first.date.isoformat() == "2021-12-14" and first.url.endswith(".pdf")
    assert first.kind == "court_decision" and first.flags == ["court"]
    assert "verify the parties" in first.source
    assert second.title.startswith("Genf") and second.summary == "C/3570/2010"


def test_swiss_courts_skip_short_names():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().mock(return_value=httpx.Response(500))
        assert SwissCourtsConnector(LIVE).get_documents(company("ABB")) == []
        assert not route.called


@respx.mock
def test_courtlistener_opinions():
    route = respx.get("https://www.courtlistener.com/api/rest/v4/search/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 201,
                "results": [
                    {
                        "absolute_url": "/opinion/5287561/glencore-ltd-v-freepoint-commodities-llc/",
                        "caseName": "Glencore Ltd. v. Freepoint Commodities LLC",
                        "court": "Appellate Division of the Supreme Court of the State of New York",
                        "dateFiled": "2021-10-05",
                        "docketNumber": "Index No. 653431/19",
                    }
                ]
                + [{"caseName": f"Case {i}", "dateFiled": None} for i in range(12)],
            },
        )
    )
    docs = CourtListenerConnector(LIVE).get_documents(person("Ivan Glasenberg", qid="Q1680473"))
    params = route.calls[0].request.url.params
    assert params["q"] == '"Ivan Glasenberg"' and params["type"] == "o"
    assert len(docs) == 8
    doc = docs[0]
    assert doc.url == (
        "https://www.courtlistener.com/opinion/5287561/glencore-ltd-v-freepoint-commodities-llc/"
    )
    assert doc.date.isoformat() == "2021-10-05" and "653431/19" in doc.summary
    assert doc.kind == "court_decision" and doc.flags == ["court"]


# ---------------------------------------------------------------------- TED
@respx.mock
def test_ted_contracts_awarded():
    route = respx.post("https://api.ted.europa.eu/v3/notices/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "notices": [
                    {
                        "notice-type": "can-standard",
                        "publication-number": "100-2021",
                        "buyer-name": {"fra": ["Ville de Paris"]},
                        "publication-date": "2021-02-01Z",
                        "links": {},
                    },
                    {
                        "notice-type": "can-standard",
                        "contract-conclusion-date": ["2023-06-23+03:00"],
                        "publication-number": "422820-2023",
                        "buyer-name": {"est": ["Riigi Kaitseinvesteeringute Keskus"]},
                        "buyer-country": ["EST"],
                        "publication-date": "2023-07-12Z",
                        "total-value": [1250000.0],
                        "total-value-cur": ["EUR"],
                        "notice-title": {"eng": "Estonia – Fuels", "est": "Kütused"},
                        "links": {
                            "html": {
                                "DEU": "https://ted.europa.eu/de/notice/-/detail/422820-2023",
                                "ENG": "https://ted.europa.eu/en/notice/-/detail/422820-2023",
                            }
                        },
                    },
                ],
                "totalNoticeCount": 2,
            },
        )
    )
    newest, oldest = TedConnector(LIVE).get_documents(company("Acme Fuels AS"))
    body = json.loads(route.calls[0].request.content)
    assert body["query"] == 'winner-name = "Acme Fuels AS"' and body["scope"] == "ALL"
    assert newest.title == "Contract awarded by Riigi Kaitseinvesteeringute Keskus (EST)"
    assert newest.date.isoformat() == "2023-07-12"
    assert newest.url == "https://ted.europa.eu/en/notice/-/detail/422820-2023"
    assert "1 250 000 EUR" in newest.summary and "Estonia – Fuels" in newest.summary
    assert newest.kind == "public_contract" and newest.flags == ["public_contract"]
    assert oldest.title == "Contract awarded by Ville de Paris"
    assert oldest.url == "https://ted.europa.eu/en/notice/-/detail/100-2021"


def test_ted_companies_only():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().mock(return_value=httpx.Response(500))
        assert TedConnector(LIVE).get_documents(person("Ivan Glasenberg", qid="Q1")) == []
        assert not route.called


# ---------------------------------------------------------------- LittleSis
LS_SEARCH = {
    "meta": {"currentPage": 1, "pageCount": 1},
    "data": [
        {
            "type": "entities",
            "id": 11,
            "attributes": {"id": 11, "name": "Glencore Plc", "primary_ext": "Person"},
        },
        {
            "type": "entities",
            "id": 12,
            "attributes": {"id": 12, "name": "Glencore Agriculture", "primary_ext": "Org"},
        },
        {
            "type": "entities",
            "id": 93387,
            "attributes": {
                "id": 93387,
                "name": "Glencore Plc",
                "blurb": "British–Swiss multinational commodity trading and mining company",
                "primary_ext": "Org",
                "aliases": ["Glencore Plc", "Glencore International plc"],
            },
            "links": {"self": "https://littlesis.org/entities/93387-Glencore_Plc"},
        },
    ],
}
LS_RELATIONSHIPS = {
    "data": [
        {
            "type": "relationships",
            "id": 1762552,
            "attributes": {
                "id": 1762552,
                "start_date": "2010-05-00",
                "end_date": "2013-05-00",
                "is_current": None,
                "amount": None,
                "currency": None,
                "description": "Jonathan Goldberg  has/had a position (Partner) at  Glencore Plc ",
            },
            "self": "https://littlesis.org/relationships/1762552",
        },
        {
            "type": "relationships",
            "id": 2,
            "attributes": {
                "start_date": None,
                "is_current": True,
                "amount": 50000,
                "currency": "usd",
                "description": "Glencore Plc  gave money to  Some PAC",
            },
        },
    ]
    + [
        {"type": "relationships", "id": 100 + i, "attributes": {"description": f"Rel {i}"}}
        for i in range(20)
    ],
}


@respx.mock
def test_littlesis_profile_and_relationships():
    respx.get("https://littlesis.org/api/entities/search").mock(
        return_value=httpx.Response(200, json=LS_SEARCH)
    )
    rels = respx.get("https://littlesis.org/api/entities/93387/relationships").mock(
        return_value=httpx.Response(200, json=LS_RELATIONSHIPS)
    )
    docs = LittleSisConnector(LIVE).get_documents(company("GLENCORE PLC"))
    assert rels.called
    profile, position, donation = docs[:3]
    assert len(docs) == 13  # profile + 12 relationships
    assert profile.title == "LittleSis profile: Glencore Plc" and profile.kind == "profile"
    assert profile.url == "https://littlesis.org/entities/93387-Glencore_Plc"
    assert profile.summary.startswith("British–Swiss")
    assert position.title == "Jonathan Goldberg has/had a position (Partner) at Glencore Plc"
    assert position.kind == "relationship" and position.date.isoformat() == "2010-05-01"
    assert position.summary == "ended 2013"
    assert position.url == "https://littlesis.org/relationships/1762552"
    assert donation.date is None and "current" in donation.summary and "50000" in donation.summary


@respx.mock
def test_littlesis_requires_exact_match_of_the_right_type():
    respx.get("https://littlesis.org/api/entities/search").mock(
        return_value=httpx.Response(200, json=LS_SEARCH)
    )
    rels = respx.get(url__regex=r"https://littlesis.org/api/entities/\d+/relationships").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    conn = LittleSisConnector(LIVE)
    assert conn.get_documents(company("Glencore Energy UK")) == []
    # a public figure named like an Org entry only matches Person entries
    [profile] = conn.get_documents(person("Glencore Plc", qid="Q1"))
    assert profile.url == "https://littlesis.org/entities/11"
    assert rels.call_count == 1


# ----------------------------------------------------------------- websites
def test_registrable_domain():
    assert registrable_domain("*.glencore.com") == "glencore.com"
    assert registrable_domain("a.b.Glencore.com.") == "glencore.com"
    assert registrable_domain("shop.example.co.uk") == "example.co.uk"
    assert registrable_domain("*.example.com.au") == "example.com.au"
    assert registrable_domain("co.uk") is None
    assert registrable_domain("localhost") is None


CRT = [
    {"common_name": "*.glencore.com", "name_value": "*.glencore.com\nglencore.com"},
    {"common_name": "advance.glencore.com", "name_value": "advance.glencore.com"},
    {
        "common_name": "glencore.com",
        "name_value": "glencore.com\nwww.glencore.co.uk\n*.glencore-agri.com\nmail.glencore.co.uk",
    },
]


def _hackertarget(request):
    q = request.url.params["q"]
    if q == "glencore.com":
        return httpx.Response(
            200, text="www.glencore.com\tgtm\tGTM-K6F9BXS\nwww.glencore.com\tua\tUA-1\n"
        )
    if q == "GTM-K6F9BXS":
        return httpx.Response(200, text="www.glencore.com\tgtm\nwww.sister-trading.ch\tgtm\n")
    return httpx.Response(200, text="www.glencore.com\tua\n")  # only the company itself


@respx.mock
def test_linked_websites():
    crt = respx.get("https://crt.sh/").mock(return_value=httpx.Response(200, json=CRT))
    respx.get("https://api.hackertarget.com/analyticslookup/").mock(side_effect=_hackertarget)
    docs = LinkedWebsitesConnector(LIVE).get_documents(company(website="https://www.glencore.com/"))
    assert crt.calls[0].request.url.params["q"] == "%.glencore.com"
    certs, analytics = docs
    assert certs.title == "Domains sharing TLS certificates with glencore.com"
    assert "glencore.co.uk" in certs.summary and "glencore-agri.com" in certs.summary
    assert "advance" not in certs.summary and certs.summary.startswith("2 domain(s)")
    assert certs.url == "https://crt.sh/?q=%25.glencore.com"
    assert analytics.title == "Sites sharing the analytics ID GTM-K6F9BXS"
    assert "www.sister-trading.ch" in analytics.summary
    assert all(d.kind == "website" and d.flags == ["linked_websites"] for d in docs)


@respx.mock
def test_linked_websites_quota_and_network_errors():
    respx.get("https://crt.sh/").mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get("https://api.hackertarget.com/analyticslookup/").mock(
        return_value=httpx.Response(200, text="API count exceeded - Increase Quota with Membership")
    )
    assert LinkedWebsitesConnector(LIVE).get_documents(company(website="glencore.com")) == []


def test_linked_websites_uses_official_website_documents():
    entity = company()
    entity.documents = [
        Document(title="Official website", kind="register", url="https://acme.example", source="x")
    ]
    with respx.mock(assert_all_called=False) as mock:
        crt = mock.get("https://crt.sh/").mock(return_value=httpx.Response(200, json=[]))
        mock.get("https://api.hackertarget.com/analyticslookup/").mock(
            return_value=httpx.Response(200, text="error check your search parameter")
        )
        assert LinkedWebsitesConnector(LIVE).get_documents(entity) == []
        assert crt.calls[0].request.url.params["q"] == "%.acme.example"
    # no website known: no request at all
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().mock(return_value=httpx.Response(500))
        assert LinkedWebsitesConnector(LIVE).get_documents(company()) == []
        assert not route.called
