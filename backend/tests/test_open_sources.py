"""Keyless open sources (GLEIF, BODACC, official sanctions lists) and linked documents."""

import httpx
import respx

from app.connectors import official_sanctions as osl
from app.connectors.bodacc import BodaccConnector
from app.connectors.gleif import GleifConnector
from app.graph.expander import NetworkExpander
from app.graph.links import register_links
from app.models import Entity, EntityType, ListType, RelationType
from app.risk.engine import RiskEngine
from app.settings import Settings

LIVE = Settings(live_sources=True)


def company(name, jur=None, reg=None):
    return Entity(
        id=f"x:{name}",
        type=EntityType.COMPANY,
        name=name,
        jurisdiction=jur,
        registration_number=reg,
    )


def lei_record(lei, name, reg, country="FR"):
    return {
        "type": "lei-records",
        "id": lei,
        "attributes": {
            "lei": lei,
            "entity": {
                "legalName": {"name": name},
                "registeredAs": reg,
                "jurisdiction": country,
                "status": "ACTIVE",
                "legalAddress": {
                    "addressLines": ["1 rue X"],
                    "city": "Paris",
                    "postalCode": "75001",
                    "country": country,
                },
                "creationDate": "1955-01-01T00:00:00Z",
            },
        },
    }


@respx.mock
def test_gleif_parent_and_children():
    base = "https://api.gleif.org/api/v1/lei-records"
    respx.get(f"{base}/CHILD000000000000001/direct-parent").mock(
        return_value=httpx.Response(
            200, json={"data": lei_record("PARENT00000000000001", "PARENT SA", "111111111")}
        )
    )
    respx.get(f"{base}/CHILD000000000000001/ultimate-parent").mock(
        return_value=httpx.Response(
            200, json={"data": lei_record("GROUP000000000000001", "GROUP HOLDING AG", "333333333")}
        )
    )
    respx.get(f"{base}/CHILD000000000000001/direct-children").mock(
        return_value=httpx.Response(
            200, json={"data": [lei_record("GRAND000000000000001", "GRANDCHILD SAS", "222222222")]}
        )
    )
    conn = GleifConnector(LIVE)
    parent, head = conn.get_shareholders("gleif:CHILD000000000000001")
    assert (
        parent.entity.name == "PARENT SA" and parent.relationship.type == RelationType.SHAREHOLDER
    )
    assert (
        head.entity.name == "GROUP HOLDING AG" and head.relationship.type == RelationType.CONTROLS
    )
    assert "Ultimate parent" in head.relationship.role
    assert parent.relationship.share_pct is None and "consolidation" in parent.relationship.role
    [child] = conn.get_subsidiaries("gleif:CHILD000000000000001")
    assert child.relationship.target_id == "gleif:GRAND000000000000001"
    assert child.entity.identifiers["LEI"] == "GRAND000000000000001"


@respx.mock
def test_gleif_search_puts_exact_legal_name_first():
    def reply(request):
        params = request.url.params
        if "filter[entity.legalName]" in params:
            return httpx.Response(
                200, json={"data": [lei_record("HEAD0000000000000001", "DANONE", "552032534")]}
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    lei_record("SUB00000000000000001", "FONDS DANONE", "531660702"),
                    lei_record("HEAD0000000000000001", "DANONE", "552032534"),
                ]
            },
        )

    respx.get("https://api.gleif.org/api/v1/lei-records").mock(side_effect=reply)
    found = GleifConnector(LIVE).search_company("Danone")
    assert [c.name for c in found] == ["DANONE", "FONDS DANONE"]  # head first, no duplicate


@respx.mock
def test_gleif_no_parent_reported():
    for kind in ("direct-parent", "ultimate-parent"):
        respx.get(f"https://api.gleif.org/api/v1/lei-records/X/{kind}").mock(
            return_value=httpx.Response(404)
        )
    assert GleifConnector(LIVE).get_shareholders("gleif:X") == []


@respx.mock
def test_bodacc_notices_become_documents_and_flag_insolvency():
    respx.get(url__startswith="https://bodacc-datadila.opendatasoft.com").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 3,
                "results": [
                    {
                        "id": "A1",
                        "registre": ["552 100 554", "552100554"],
                        "familleavis_lib": "Procédures collectives",
                        "typeavis_lib": "Avis initial",
                        "dateparution": "2024-02-01",
                        "tribunal": "TRIBUNAL DE COMMERCE DE PARIS",
                        "jugement": '{"nature": "Jugement d\'ouverture d\'une procédure de redressement judiciaire"}',
                        "url_complete": "https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:A1",
                    },
                    {
                        "id": "A2",
                        "registre": ["552100554"],
                        "familleavis_lib": "Dépôts des comptes",
                        "dateparution": "2023-07-10",
                        "depot": '{"dateCloture": "2022-12-31", "typeDepot": "Comptes annuels et rapports"}',
                    },
                    {
                        "id": "A3",
                        "registre": ["999999999"],
                        "familleavis_lib": "Immatriculations",
                        "dateparution": "2020-01-01",
                    },
                ],
            },
        )
    )
    docs = BodaccConnector(LIVE).get_documents(company("ACME", "FR", "552 100 554"))
    assert [d.kind for d in docs] == [
        "insolvency",
        "accounts",
    ]  # the other company's notice is dropped
    assert docs[0].flags == ["insolvency"] and "redressement judiciaire" in docs[0].summary
    assert "2022-12-31" in docs[1].summary and docs[0].url.endswith("id:A1")


def test_bodacc_ignores_non_french_companies():
    assert BodaccConnector(LIVE).get_documents(company("ACME LTD", "GB", "01234567")) == []


def test_register_links_by_jurisdiction():
    fr = register_links(company("ACME", "FR", "552 100 554"))
    assert any("data.inpi.fr/entreprises/552100554" in d.url for d in fr)
    gb = register_links(company("ACME LTD", "GB", "01234567"))
    assert any(d.url.endswith("/company/01234567/filing-history") for d in gb)
    demo = company("ACME", "FR", "552100554")
    demo.demo = True
    assert register_links(demo) == []


SDN = """36,"PUTIN, Vladimir Vladimirovich","individual","RUSSIA-EO14024","President of the Russian Federation",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"DOB 07 Oct 1952; POB Leningrad, Russia; nationality Russia; Gender Male."
99,"ACME SHIPPING LLC","-0- ","SDGT",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"Linked To: SOMEONE."
"""
ALT = """36,1,"aka","PUTIN, Vladimir",-0-
"""
UN = """<CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL><REFERENCE_NUMBER>QDi.001</REFERENCE_NUMBER>
<FIRST_NAME>AYMAN</FIRST_NAME><SECOND_NAME>AL-ZAWAHIRI</SECOND_NAME><UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE>
<LISTED_ON>2001-01-25</LISTED_ON><NATIONALITY><VALUE>Egypt</VALUE></NATIONALITY>
<INDIVIDUAL_ALIAS><ALIAS_NAME>Ayman al-Zawahry</ALIAS_NAME></INDIVIDUAL_ALIAS>
<INDIVIDUAL_DATE_OF_BIRTH><DATE>1951-06-19</DATE></INDIVIDUAL_DATE_OF_BIRTH></INDIVIDUAL></INDIVIDUALS>
<ENTITIES><ENTITY><REFERENCE_NUMBER>QDe.004</REFERENCE_NUMBER><FIRST_NAME>AL RASHID TRUST</FIRST_NAME></ENTITY></ENTITIES>
</CONSOLIDATED_LIST>"""


@respx.mock
def test_official_sanctions_lists_download_index_and_match(monkeypatch):
    monkeypatch.setattr(osl, "_INDEX", osl._Index())
    respx.get(osl.OFAC_SDN).mock(return_value=httpx.Response(200, text=SDN))
    respx.get(osl.OFAC_ALT).mock(return_value=httpx.Response(200, text=ALT))
    respx.get(osl.UN_XML).mock(return_value=httpx.Response(200, text=UN))
    conn = osl.OfficialSanctionsConnector(LIVE)

    putin = Entity(id="p", type=EntityType.PERSON, name="Vladimir Putin", birth_date="1952-10-07")
    [hit] = conn.screen(putin)
    assert hit.list_type == ListType.SANCTION and hit.dataset.startswith("OFAC") and hit.score >= 95
    assert hit.details["program"] == "RUSSIA-EO14024" and hit.provenance.url.endswith("id=36")

    [un] = conn.screen(Entity(id="z", type=EntityType.PERSON, name="Ayman al Zawahry"))
    assert un.dataset.startswith("UN Security Council") and un.details["reference"] == "QDi.001"
    assert conn.screen(company("Al Rashid Trust"))[0].matched_name == "AL RASHID TRUST"
    namesake = Entity(
        id="n", type=EntityType.PERSON, name="Vladimir Putin", birth_date="1990-01-01"
    )
    assert all(h.score < 70 for h in conn.screen(namesake))  # different date of birth


def test_demo_documents_and_insolvency_flag(registry):
    seed = registry.connectors["demo_fr_registry"].get_person_details("demo_fr_registry:P-001")
    net = NetworkExpander(registry, max_depth=1, max_nodes=50).expand([seed])
    batiprest = next(e for e in net.entities.values() if e.name.startswith("Batiprest"))
    assert any("insolvency" in d.flags for d in batiprest.documents)
    assert all(d.source for d in batiprest.documents)
    factors = {f.key: f for f in RiskEngine().assess(net).factors}
    assert (
        "insolvency_proceedings" in factors
        and "liquidation" in factors["insolvency_proceedings"].evidence[0]
    )
