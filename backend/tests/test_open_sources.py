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
    for url in (osl.EU_XML, osl.UK_XML, osl.CH_XML):
        respx.get(url).mock(return_value=httpx.Response(404))
    respx.get(url__startswith="https://data.opensanctions.org/").mock(
        return_value=httpx.Response(404)
    )
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


EU_FSF = """<?xml version="1.0" encoding="UTF-8"?>
<export xmlns="http://eu.europa.ec/fpi/fsd/export">
<sanctionEntity euReferenceNumber="EU.27.28" logicalId="13">
  <remark>UNSC RESOLUTION 1483</remark>
  <regulation programme="IRQ" logicalId="348"><publicationUrl>http://eur-lex.europa.eu/act.pdf</publicationUrl></regulation>
  <subjectType code="person" classificationCode="P"/>
  <nameAlias wholeName="Saddam Hussein Al-Tikriti" strong="true"/>
  <nameAlias wholeName="Abu Ali" strong="true"/>
  <citizenship countryIso2Code="IQ"/>
  <birthdate birthdate="1937-04-28" year="1937"/>
</sanctionEntity>
<sanctionEntity euReferenceNumber="EU.1.1" logicalId="99">
  <regulation programme="RUS"/>
  <subjectType code="enterprise" classificationCode="E"/>
  <nameAlias wholeName="Example Defence Plant JSC"/>
</sanctionEntity>
</export>"""

UK_LIST = """<?xml version="1.0" encoding="utf-8"?>
<Designations><DateGenerated>21/09/2026</DateGenerated>
<Designation><UniqueID>AFG0006</UniqueID><DateDesignated>25/01/2001</DateDesignated>
  <Names><Name><Name1>MOHAMMAD</Name1><Name2>HASSAN</Name2><Name6>AKHUND</Name6><NameType>Primary Name</NameType></Name>
  <Name><Name6>Mullah Mohammad Hassan</Name6><NameType>Alias</NameType></Name></Names>
  <RegimeName>The Afghanistan (Sanctions) (EU Exit) Regulations 2020</RegimeName>
  <IndividualEntityShip>Individual</IndividualEntityShip><SanctionsImposed>Asset freeze|Travel Ban</SanctionsImposed>
  <IndividualDetails><Individual><DOBs><DOB>dd/mm/1945</DOB></DOBs>
  <Nationalities><Nationality>Afghanistan</Nationality></Nationalities></Individual></IndividualDetails>
</Designation>
<Designation><UniqueID>RUS9999</UniqueID><Names><Name><Name6>SOME TANKER</Name6><NameType>Primary Name</NameType></Name></Names>
  <IndividualEntityShip>Ship</IndividualEntityShip></Designation>
</Designations>"""

CH_LIST = """<?xml version="1.0" encoding="UTF-8"?><swiss-sanctions-list list-type="whole-list">
<sanctions-program ssid="20"><program-key lang="eng">Belarus</program-key>
  <sanctions-set ssid="4387" lang="eng">annexe 13</sanctions-set></sanctions-program>
<target ssid="100"><sanctions-set-id>4387</sanctions-set-id>
  <modification modification-type="listed" effective-date="2022-03-16"/>
  <individual><identity ssid="1" main="true">
    <name name-type="primary-name"><name-part order="1" name-part-type="family-name"><value>Lukashenka</value>
      <spelling-variant script="LATN">Lukashenko</spelling-variant><spelling-variant script="CYRL">ЛУКАШЕНКО</spelling-variant></name-part>
    <name-part order="2" name-part-type="given-name"><value>Aliaksandr</value>
      <spelling-variant script="LATN">Alexander</spelling-variant></name-part></name>
    <day-month-year day="30" month="8" year="1954"/>
    <nationality ssid="9"><country iso-code="BY">Belarus</country></nationality></identity>
  <justification>President.</justification></individual>
</target>
<target ssid="5144"><sanctions-set-id>4387</sanctions-set-id>
  <individual><identity ssid="2" main="true"><name name-type="primary-name">
    <name-part order="1"><value>Lukashenka</value></name-part><name-part order="2"><value>Dzmitry</value></name-part></name></identity></individual>
  <modification modification-type="de-listed" effective-date="2016-03-01"/>
  <modification modification-type="amended" effective-date="2015-11-18"><added><individual/></added></modification>
</target>
</swiss-sanctions-list>"""


@respx.mock
def test_official_eu_uk_swiss_lists(monkeypatch):
    monkeypatch.setattr(osl, "_INDEX", osl._Index())
    for url in (osl.OFAC_SDN, osl.OFAC_ALT, osl.UN_XML):
        respx.get(url).mock(return_value=httpx.Response(404))
    respx.get(url__startswith="https://data.opensanctions.org/").mock(
        return_value=httpx.Response(404)
    )
    respx.get(osl.EU_XML).mock(return_value=httpx.Response(200, text=EU_FSF))
    respx.get(osl.UK_XML).mock(return_value=httpx.Response(200, text=UK_LIST))
    respx.get(osl.CH_XML).mock(return_value=httpx.Response(200, text=CH_LIST))
    monkeypatch.setattr(osl, "_INDEX_EUROPE", osl._Index())
    conn = osl.EuropeanSanctionsConnector(LIVE)

    [eu] = conn.screen(Entity(id="s", type=EntityType.PERSON, name="Saddam Hussein Al Tikriti"))
    assert eu.dataset.startswith("EU consolidated") and eu.details["program"] == "IRQ"
    assert eu.details["birth_date"] == "1937-04-28" and eu.details["nationalities"] == ["IQ"]
    assert eu.provenance.url == "http://eur-lex.europa.eu/act.pdf"
    assert conn.screen(company("Example Defence Plant"))[0].details["reference"] == "EU.1.1"

    [uk] = conn.screen(Entity(id="a", type=EntityType.PERSON, name="Mohammad Hassan Akhund"))
    assert uk.dataset == "UK Sanctions List (FCDO)" and uk.details["birth_date"] == "1945"
    assert uk.details["nationalities"] == ["AF"] and uk.details["sanctions"].startswith("Asset")
    assert conn.screen(company("Some Tanker")) == []  # ships are not indexed

    hits = conn.screen(Entity(id="l", type=EntityType.PERSON, name="Alexander Lukashenko"))
    assert [h.details["reference"] for h in hits] == ["100"]  # the de-listed target is skipped
    assert hits[0].details["program"] == "Belarus" and hits[0].details["birth_date"] == "1954-08-30"
    assert hits[0].matched_name == "Aliaksandr Lukashenka"
    assert hits[0].details["nationalities"] == ["BY"]
    assert osl._uk_dob("23/03/1980") == "1980-03-23" and osl._uk_dob("dd/03/1980") == "1980-03"


@respx.mock
def test_european_download_is_retried_and_last_good_copy_kept(monkeypatch):
    monkeypatch.setattr(osl, "_INDEX_EUROPE", osl._Index())
    monkeypatch.setattr(osl, "DOWNLOAD_BACKOFF_SECONDS", 0)
    respx.get(osl.EU_XML).mock(return_value=httpx.Response(200, text=EU_FSF))
    respx.get(osl.UK_XML).mock(return_value=httpx.Response(200, text=UK_LIST))
    ch = respx.get(osl.CH_XML).mock(
        side_effect=[
            httpx.RemoteProtocolError("peer closed connection"),
            httpx.Response(200, text=CH_LIST),
        ]
    )
    conn = osl.EuropeanSanctionsConnector(LIVE)
    lukashenko = Entity(id="l", type=EntityType.PERSON, name="Alexander Lukashenko")
    assert conn.screen(lukashenko) and ch.call_count == 2  # the dropped transfer was retried
    assert not osl._INDEX_EUROPE.errors

    # Next refresh: SECO keeps failing. Its last good copy stays in the screening.
    ch.side_effect = httpx.RemoteProtocolError("peer closed connection")
    osl._INDEX_EUROPE.loaded_at = 0
    assert conn.screen(lukashenko)
    [err] = osl._INDEX_EUROPE.errors
    assert err.startswith("CH list unavailable") and "the copy downloaded on" in err


CSL = {
    "results": [
        {
            "id": "e1",
            "name": "Huawei Technologies Co., Ltd.",
            "alt_names": ["Huawei"],
            "source": "Entity List (EL) - Bureau of Industry and Security",
            "addresses": [{"country": "CN"}],
            "start_date": "2019-05-16",
            "source_information_url": "https://www.bis.gov/entity-list",
        },
        {
            "id": "p1",
            "name": "Chris Tang",
            "type": "Individual",
            "dates_of_birth": ["1965-07-04"],
            "source": "Non-SDN Menu-Based Sanctions List (NS-MBS List) - Treasury Department",
            "programs": ["HKAA"],
        },
        {
            "id": "u1",
            "name": "Mystery Buyer",
            "source": "Unverified List (UVL) - Bureau of Industry and Security",
        },
        {
            "id": "s1",
            "name": "Already On SDN",
            "type": "Individual",
            "source": "Specially Designated Nationals (SDN) - Treasury Department",
        },
    ]
}
FR = {
    "Publications": {
        "PublicationDetail": [
            {
                "IdRegistre": 4240,
                "Nature": "Personne physique",
                "Nom": "SHILKIN",
                "RegistreDetail": [
                    {"TypeChamp": "PRENOM", "Valeur": [{"Prenom": "Grigory Vladimirovich"}]},
                    {
                        "TypeChamp": "DATE_DE_NAISSANCE",
                        "Valeur": [{"Jour": "20", "Mois": "10", "Annee": "1976"}],
                    },
                    {"TypeChamp": "NATIONALITE", "Valeur": [{"Pays": "RUSSIE"}]},
                    {
                        "TypeChamp": "FONDEMENT_JURIDIQUE",
                        "Valeur": [{"FondementJuridiqueLabel": "(UE) 2022/332 du 25/02/2022"}],
                    },
                ],
            },
            {
                "IdRegistre": 7805,
                "Nature": "Personne morale",
                "Nom": "JSC Gruppa Kremniy El",
                "RegistreDetail": [
                    {
                        "TypeChamp": "FONDEMENT_JURIDIQUE",
                        "Valeur": [{"FondementJuridiqueLabel": "Arrêté national du 1er mars 2024"}],
                    },
                ],
            },
            {"IdRegistre": 9, "Nature": "Navire", "Nom": "Some Tanker", "RegistreDetail": []},
        ]
    }
}


@respx.mock
def test_us_screening_list_and_french_freezes(monkeypatch):
    monkeypatch.setattr(osl, "_INDEX_NATIONAL", osl._Index())
    respx.get(osl.US_CSL).mock(return_value=httpx.Response(200, json=CSL))
    respx.get(osl.FR_GELS).mock(return_value=httpx.Response(200, json=FR))
    conn = osl.NationalSanctionsConnector(LIVE)

    [huawei] = conn.screen(company("Huawei Technologies Co Ltd"))
    assert huawei.dataset.startswith("US Entity List") and huawei.details["countries"] == "CN"
    [tang] = conn.screen(Entity(id="t", type=EntityType.PERSON, name="Chris Tang"))
    assert tang.details["program"] == "HKAA" and tang.details["birth_date"] == "1965-07-04"
    # no type on the Commerce lists: found as a person and as a company, flagged as a watchlist
    assert conn.screen(company("Mystery Buyer"))[0].list_type.value == "adverse"
    assert conn.screen(Entity(id="m", type=EntityType.PERSON, name="Mystery Buyer"))
    assert (
        conn.screen(Entity(id="s", type=EntityType.PERSON, name="Already On SDN")) == []
    )  # read from OFAC

    [shilkin] = conn.screen(Entity(id="g", type=EntityType.PERSON, name="Grigory Shilkin"))
    assert shilkin.dataset.startswith("France asset freezes")
    assert shilkin.details["birth_date"] == "1976-10-20" and shilkin.details["nationalities"] == [
        "RU"
    ]
    assert "national_measure" not in shilkin.details  # an EU measure
    [kremniy] = conn.screen(company("JSC Gruppa Kremniy El"))
    assert kremniy.details["national_measure"] == "yes"
    assert conn.screen(company("Some Tanker")) == []  # ships are not indexed
