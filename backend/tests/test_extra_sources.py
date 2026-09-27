"""UID register, Lobbywatch, Bundestag Lobbyregister, ESMA MiCA, ASIC, scam lists, the
Guardian, French domiciliation search and the quick checks (IBAN, e-mail, wallet).
Answers mirror the real services (probed live)."""

import json

import httpx
import pytest
import respx

from app import checks
from app.connectors import annuaire_fr
from app.connectors import extra_sources as es
from app.identifiers import Identifier
from app.models import CompanyStatus, Document, Entity, EntityType, ListType, RelationType
from app.settings import Settings

LIVE = Settings(live_sources=True)
KEYED = Settings(live_sources=True, guardian_api_key="k")


@pytest.fixture(autouse=True)
def fresh_lists():
    for lazy in (es._MICA, es._ASIC, es._SCAM_DOMAINS, es._SCAM_ADDRESSES):
        lazy.value, lazy.loaded_at = None, 0.0
    checks._CACHE.clear()
    yield


def _company(name, **kw):
    return Entity(id=f"x:{name}", type=EntityType.COMPANY, name=name, **kw)


def _person(name, **kw):
    return Entity(id=f"x:{name}", type=EntityType.PERSON, name=name, **kw)


# ------------------------------------------------------------------------ UID register
UID_ANSWER = """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
<SearchResponse xmlns="http://www.uid.admin.ch/xmlns/uid-wse"><SearchResult>
<organisationType><organisation xmlns="http://www.ech.ch/xmlns/eCH-0108-f/3">
<organisationIdentification xmlns="http://www.ech.ch/xmlns/eCH-0098-f/3">
<uid xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2"><uidOrganisationIdCategorie>CHE</uidOrganisationIdCategorie>
<uidOrganisationId>116281710</uidOrganisationId></uid>
<organisationName xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2">Fondation Alpha Genève</organisationName>
<legalForm xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2">0110</legalForm></organisationIdentification>
<contact xmlns="http://www.ech.ch/xmlns/eCH-0098-f/3"><address xmlns="http://www.ech.ch/xmlns/eCH-0046-f/3">
<postalAddress><addressInformation xmlns="http://www.ech.ch/xmlns/eCH-0010-f/6"><street>Rue du Rhône</street>
<houseNumber>8</houseNumber><town>Genève</town><swissZipCode>1204</swissZipCode></addressInformation>
</postalAddress></address></contact></organisation>
<uidregInformation xmlns="http://www.ech.ch/xmlns/eCH-0108-f/3"><uidregStatusEnterpriseDetail>3</uidregStatusEnterpriseDetail></uidregInformation>
<vatRegisterInformation xmlns="http://www.ech.ch/xmlns/eCH-0108-f/3"><vatStatus>2</vatStatus><vatEntryDate>2015-01-01</vatEntryDate></vatRegisterInformation>
</organisationType>
<organisationType><organisation xmlns="http://www.ech.ch/xmlns/eCH-0108-f/3">
<organisationIdentification xmlns="http://www.ech.ch/xmlns/eCH-0098-f/3">
<uid xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2"><uidOrganisationId>106547415</uidOrganisationId></uid>
<organisationName xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2">A. Lemmenmeier</organisationName></organisationIdentification>
</organisation></organisationType>
</SearchResult></SearchResponse></s:Body></s:Envelope>"""


@respx.mock
def test_uid_register_finds_foundations_outside_the_commercial_register():
    route = respx.post(es.UID_WS).mock(return_value=httpx.Response(200, text=UID_ANSWER))
    found = es.UidRegisterConnector(LIVE).search_company("Fondation Alpha Genève")
    assert b"<ns:organisationName>Fondation Alpha Gen" in route.calls[0].request.content
    assert route.calls[0].request.headers["SOAPAction"].endswith("/Search")
    assert len(found) == 1  # the unrelated sole trader is filtered out
    f = found[0]
    assert (f.registration_number, f.identifiers["UID"]) == ("CHE-116.281.710", "CHE-116.281.710")
    assert f.legal_form == "Foundation" and f.status == CompanyStatus.ACTIVE
    assert f.address == "Rue du Rhône 8, 1204 Genève"
    assert f.extra["vat_status"] == "registered for VAT"
    assert f.extra["commercial_register"].startswith("no")
    doc = es.UidRegisterConnector(LIVE).get_documents(f)[0]
    assert "registered for VAT" in doc.summary and "VAT since 2015-01-01" in doc.summary


@respx.mock
def test_uid_register_lookup_by_uid():
    route = respx.post(es.UID_WS).mock(return_value=httpx.Response(200, text=UID_ANSWER))
    ent = es.UidRegisterConnector(LIVE).get_by_identifier(
        Identifier("ch_uid", "CHE-116.281.710", "Swiss UID")
    )
    assert "<uidOrganisationId" in route.calls[0].request.content.decode()
    assert route.calls[0].request.headers["SOAPAction"].endswith("/GetByUID")
    assert ent.name == "Fondation Alpha Genève"


# -------------------------------------------------------------------------- Lobbywatch
LW_ORG = {
    "id": "8765",
    "name": "RUAG International Holding AG",
    "uid": "CHE-405.231.023",
    "land_id": "191",
    "rechtsform": "AG",
    "ort": "Bern",
    "lobbyeinfluss": "hoch",
    "interessengruppe": "Rüstung",
}
LW_PARL = {
    "id": "166",
    "name": "Gerhard Pfister",
    "vorname": "Gerhard",
    "nachname": "Pfister",
    "geburtstag": "1962-10-01",
    "rat": "NR",
    "kanton": "ZG",
    "partei_name": "Die Mitte",
    "im_rat_seit": "2003-12-01",
    "wikidata_qid": "Q1387808",
    "email": "private@example.ch",
    "telephon_1": "+41 00 000 00 00",
    "interessenbindungen": [
        {
            "id": "14555",
            "organisation_id": "8765",
            "organisation_name": "RUAG International Holding AG",
            "name": "RUAG International Holding AG",
            "uid": "CHE-405.231.023",
            "art": "vorstand",
            "funktion_im_gremium": "praesident",
            "verguetung": "20000",
            "quelle_url": "https://example.ch/source",
        }
    ],
}


def _lw(url_part: str, data):
    return respx.get(url__startswith=f"{es.LOBBYWATCH}/{url_part}").mock(
        return_value=httpx.Response(200, json={"success": True, "data": data})
    )


@respx.mock
def test_lobbywatch_parliamentarians_and_their_declared_interests():
    _lw("table/parlamentarier/flat/list/Pfister", [LW_PARL])
    _lw("table/parlamentarier/aggregated/id/166", LW_PARL)
    conn = es.LobbywatchConnector(LIVE)
    [p] = conn.search_person("Gerhard Pfister")
    assert p.birth_date == "1962-10-01" and p.identifiers == {"Wikidata": "Q1387808"}
    assert p.extra["pep_position"] == "Member of the Swiss Federal Assembly (National Council — ZG)"
    assert "private@example.ch" not in json.dumps(p.model_dump(mode="json"))  # no contact details
    [link] = conn.get_person_roles(p.id)
    assert link.relationship.type == RelationType.OFFICER
    assert link.relationship.role.startswith("Board member (Chair), paid CHF 20000")
    assert link.entity.identifiers == {"UID": "CHE-405.231.023"}  # merges with Zefix
    assert link.relationship.source_id == p.id
    assert conn.search_person("Pfister") == []  # one-word names are not searched


@respx.mock
def test_lobbywatch_organisation_links_and_document():
    _lw(
        "table/organisation/flat/list/RUAG",
        [LW_ORG, {**LW_ORG, "id": "9", "name": "Ruag Veterans Club"}],
    )
    _lw(
        "table/organisation/aggregated/id/8765",
        {
            **LW_ORG,
            "parlamentarier": [
                {
                    "parlamentarier_id": "166",
                    "anzeige_name": "14555, Pfister, Gerhard, RUAG, vorstand",
                    "art": "vorstand",
                }
            ],
            "zutrittsberechtigte": [{"id": "1"}, {"id": "2"}],
        },
    )
    conn = es.LobbywatchConnector(LIVE)
    [org] = conn.search_company("RUAG International Holding AG")
    assert org.jurisdiction == "CH" and org.registration_number == "CHE-405.231.023"
    [officer] = conn.get_officers(org.id)
    assert officer.entity.name == "Gerhard Pfister" and officer.relationship.target_id == org.id
    [doc] = conn.get_documents(org)
    assert doc.flags == ["lobbying"]
    assert "1 federal parliamentarian(s)" in doc.summary and "2 lobbyist(s)" in doc.summary


# ------------------------------------------------------------------ Bundestag register
@respx.mock
def test_bundestag_lobbyregister_reports_spend_and_code_violations():
    respx.get(url__startswith=es.LOBBYREGISTER).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "registerNumber": "R001875",
                        "registerEntryDetails": {
                            "detailsPageUrl": "https://www.lobbyregister.bundestag.de/suche/R001875/85007"
                        },
                        "accountDetails": {
                            "activeLobbyist": True,
                            "firstPublicationDate": "2022-02-28T08:25:46.576+01:00",
                            "accountHasCodexViolations": True,
                        },
                        "lobbyistIdentity": {"name": "Siemens AG"},
                        "employeesInvolvedInLobbying": {"employeeFTE": 2.49},
                        "financialExpenses": {
                            "financialExpensesEuro": {"from": 1200001, "to": 1210000}
                        },
                        "activitiesAndInterests": {"fieldsOfInterest": [{}, {}]},
                        "regulatoryProjects": {"regulatoryProjectsCount": 35},
                    },
                    {
                        "registerNumber": "R2",
                        "lobbyistIdentity": {"name": "Miller & Meier Consulting GmbH"},
                    },
                ]
            },
        )
    )
    [doc] = es.BundestagLobbyregisterConnector(LIVE).get_documents(_company("Siemens AG"))
    assert doc.flags == ["lobbying", "register_warning"]
    assert doc.summary.startswith("CODE OF CONDUCT VIOLATION")
    assert "€1 200 001–1 210 000" in doc.summary and "2.49 FTE" in doc.summary
    assert doc.date.isoformat() == "2022-02-28"


# ------------------------------------------------------------------------------ MiCA
CASPS = (
    "﻿ae_competentAuthority,ae_homeMemberState,ae_lei_name,ae_lei,ae_lei_cou_code,ae_commercial_name,"
    "ae_address,ae_website,ae_website_platform,ac_authorisationNotificationDate,ac_authorisationEndDate,"
    "ac_serviceCode,ac_serviceCode_cou,ac_comments,ac_lastupdate,\n"
    'Austrian Financial Market Authority (FMA),AT,Bitpanda GmbH,5493007WZ7IFULIL8G21,AT,Bitpanda,"Vienna",'
    "https://www.bitpanda.com,,09/04/2025,,a. providing custody | c. exchange of crypto-assets for funds,AT|BE|FR,,18/04/2025,\n"
)
NCASP = (
    "﻿ae_competentAuthority,ae_homeMemberState,ae_lei_name,ae_lei,ae_lei_cou_code,ae_commercial_name,"
    "ae_website,ae_infrigment,ae_reason,ae_decision_date,ae_comments,ae_lastupdate\n"
    "Financial Services and Markets Authority (FSMA),BE,Bank Bit,,BE,Bank Bit,www.bank-bit.com,No,"
    "Bank Bit provides crypto-asset services in Belgium without the required MiCAR license,29/06/2026,FSMA warning,07/09/2026\n"
)


def _mica():
    respx.get(es.MICA_PAGE).mock(
        return_value=httpx.Response(
            200,
            text='<a href="/sites/default/files/2025-01/CASPS.csv">x</a><a href="/sites/default/files/2025-01/NCASP.csv">y</a>',
        )
    )
    respx.get("https://www.esma.europa.eu/sites/default/files/2025-01/CASPS.csv").mock(
        return_value=httpx.Response(200, text=CASPS)
    )
    respx.get("https://www.esma.europa.eu/sites/default/files/2025-01/NCASP.csv").mock(
        return_value=httpx.Response(200, text=NCASP)
    )


@respx.mock
def test_mica_authorised_casp_is_a_register_entry_not_an_alert():
    _mica()
    conn = es.MicaRegisterConnector(LIVE)
    bitpanda = _company("Bitpanda GmbH", identifiers={"LEI": "5493007WZ7IFULIL8G21"})
    assert conn.screen(bitpanda) == []
    [doc] = conn.get_documents(bitpanda)
    assert doc.kind == "register" and doc.date.isoformat() == "2025-04-09"
    assert "authorised by Austrian Financial Market Authority (FMA)" in doc.summary
    assert "passported to 3 countries" in doc.summary


@respx.mock
def test_mica_non_compliant_entity_is_an_alert_matched_by_website():
    _mica()
    shady = _company(
        "BB Trading Ltd",
        documents=[
            Document(
                title="Official website", kind="website", url="https://bank-bit.com", source="x"
            )
        ],
    )
    [hit] = es.MicaRegisterConnector(LIVE).screen(shady)
    assert hit.list_type == ListType.ADVERSE and hit.score == 95
    assert hit.details["decision_date"] == "2026-06-29"
    assert "without the required MiCAR license" in hit.details["reason"]


# ------------------------------------------------------------------------------ ASIC
@respx.mock
def test_asic_banned_persons_screening():
    respx.get(es.ASIC_PACKAGE).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {"resources": [{"format": "CSV", "url": "https://data.gov.au/bd.csv"}]}
            },
        )
    )
    respx.get("https://data.gov.au/bd.csv").mock(
        return_value=httpx.Response(
            200,
            text="﻿REGISTER_NAME,BD_PER_NAME,BD_PER_TYPE,BD_PER_DOC_NUM,BD_PER_START_DT,BD_PER_END_DT,"
            "BD_PER_ADD_LOCAL,BD_PER_ADD_STATE,BD_PER_ADD_PCODE,BD_PER_ADD_COUNTRY,BD_PER_COMMENTS\n"
            '"Banned and Disqualified Persons","AITKEN, WARREN JOHN","Banned Securities","#014859572",'
            '"28/03/2001","","MAWSON","ACT","2607","AUSTRALIA","No comment made"\n',
        )
    )
    conn = es.AsicBannedConnector(LIVE)
    [hit] = conn.screen(_person("Warren John Aitken"))
    assert hit.dataset.startswith("ASIC") and hit.details["from"] == "2001-03-28"
    assert "until" not in hit.details
    assert conn.screen(_person("Warren Buffett")) == []
    assert conn.screen(_company("Aitken Pty Ltd")) == []


# ------------------------------------------------------------------------ scam lists
def _scam_lists():
    respx.get(es.METAMASK).mock(
        return_value=httpx.Response(
            200, json={"blacklist": ["evil-wallet.io", "opensea.pro"], "whitelist": ["opensea.pro"]}
        )
    )
    respx.get(es.SCAMSNIFFER_DOMAINS).mock(return_value=httpx.Response(200, json=["drainer.xyz"]))
    respx.get(es.SCAMSNIFFER_ADDRESSES).mock(
        return_value=httpx.Response(200, json=["0x101ce0cedd142f199c9ef61739ae59b6611a0fc0"])
    )


@respx.mock
def test_scam_lists_flag_websites_and_wallets():
    _scam_lists()
    conn = es.ScamListsConnector(LIVE)
    site = _company(
        "Evil Ltd",
        documents=[
            Document(
                title="Official website",
                kind="website",
                url="https://app.evil-wallet.io",
                source="x",
            )
        ],
    )
    [hit] = conn.screen(site)
    assert hit.list_type == ListType.ADVERSE and "MetaMask" in hit.dataset
    assert conn.domain_hits("opensea.pro") is None  # whitelisted by MetaMask
    wallet = Entity(
        id="w",
        type=EntityType.WALLET,
        name="0x101ce0cedd142f199c9ef61739ae59b6611a0fc0",
        chain="ETH",
    )
    assert conn.screen(wallet)[0].dataset.startswith("ScamSniffer")


# ------------------------------------------------------------------------- Guardian
@respx.mock
def test_guardian_needs_a_key_and_keeps_headlines_naming_the_subject():
    assert not es.GuardianConnector(LIVE).enabled
    route = respx.get(es.GUARDIAN).mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "results": [
                        {
                            "webTitle": "Glencore fined over bribery",
                            "webUrl": "https://www.theguardian.com/a",
                            "webPublicationDate": "2022-11-03T12:00:00Z",
                            "sectionName": "Business",
                        },
                        {
                            "webTitle": "Commodities round-up",
                            "webUrl": "https://www.theguardian.com/b",
                        },
                    ]
                }
            },
        )
    )
    conn = es.GuardianConnector(KEYED)
    docs = conn.get_documents(_company("Glencore"))
    assert route.calls[0].request.url.params["api-key"] == "k"
    assert [d.flags for d in docs] == [["adverse_media"], ["adverse_media", "set_aside"]]
    assert conn.get_documents(_person("Jane Private")) == []  # private persons are never searched


# ---------------------------------------------------------------- FR domiciliation
@respx.mock
def test_french_address_search_keeps_exact_address_matches_only():
    def result(siren, name, addr):
        return {
            "siren": siren,
            "nom_complet": name,
            "siege": {"adresse": addr},
            "etat_administratif": "A",
        }

    route = respx.get(url__startswith=annuaire_fr.API).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    result("111111111", "ALPHA", "60 RUE FRANCOIS IER 75008 PARIS"),
                    result("222222222", "BETA", "60 rue François 1er, 75008 Paris"),
                    result("333333333", "GAMMA", "62 RUE FRANCOIS IER 75008 PARIS"),
                ]
            },
        )
    )
    found = annuaire_fr.AnnuaireEntreprisesConnector(LIVE).search_address(
        "60 Rue François Ier 75008 Paris"
    )
    assert [c.registration_number or c.id for c in found][:1] and len(found) == 1
    assert route.calls[0].request.url.params["etat_administratif"] == "A"
    assert annuaire_fr.AnnuaireEntreprisesConnector(LIVE).search_address("Bahnhofstrasse 1") == []


# ------------------------------------------------------------------------ quick checks
def test_iban_check_digits_length_and_country():
    ok = checks.check_iban("DE89 3704 0044 0532 0130 00", client_country="CH")
    assert ok["valid"] and ok["country"]["code"] == "DE"
    labels = {c["label"]: c for c in ok["checks"]}
    assert labels["Check digits"]["status"] == "ok"
    assert "account held in" in labels["Account location"]["detail"]
    bad = checks.check_iban("DE89 3704 0044 0532 0130 01")
    assert not bad["valid"] and bad["checks"][0]["status"] == "alert"
    assert checks.check_iban("hello")["checks"][0]["label"] == "Format"


@respx.mock
def test_swiss_iban_resolves_the_bank_from_the_six_bank_master():
    respx.get(checks.SIX_BANKMASTER).mock(
        return_value=httpx.Response(
            200,
            json={
                "entries": [
                    {
                        "iid": 9000,
                        "bankOrInstitutionName": "PostFinance AG",
                        "bic": "POFICHBEXXX",
                        "townName": "Bern",
                    }
                ]
            },
        )
    )
    res = checks.check_iban("CH93 0076 2011 6238 5295 7")  # valid, clearing 00762 unknown
    assert res["valid"]
    bank = next(c for c in res["checks"] if c["label"] == "Bank")
    assert bank["status"] == "alert" and "762" in bank["detail"]
    res = checks.check_iban("CH44 0900 0000 1234 5678 9")
    assert res["country"]["code"] == "CH"


def _doh(answers):
    def handler(request):
        name, rtype = request.url.params["name"], request.url.params["type"]
        code = {"MX": 15, "TXT": 16}[rtype]
        data = answers.get((name, rtype))
        if data is None:
            return httpx.Response(200, json={"Status": 3})
        return httpx.Response(
            200, json={"Status": 0, "Answer": [{"type": code, "data": d} for d in data]}
        )

    respx.get(url__startswith=checks.DOH[0]).mock(side_effect=handler)


@respx.mock
def test_email_check_mx_spf_dmarc_age_and_free_mail():
    _scam_lists()
    respx.get(checks.DISPOSABLE).mock(return_value=httpx.Response(200, text="mailinator.com\n"))
    _doh(
        {
            ("alpha-trading.ch", "MX"): ["10 mx.alpha-trading.ch."],
            ("alpha-trading.ch", "TXT"): ['"v=spf1 include:_spf.example -all"'],
            ("_dmarc.alpha-trading.ch", "TXT"): ['"v=DMARC1; p=reject"'],
        }
    )
    respx.get(url__startswith="https://rdap.org/domain/").mock(
        return_value=httpx.Response(
            200,
            json={"events": [{"eventAction": "registration", "eventDate": "2011-05-01T00:00:00Z"}]},
        )
    )
    res = checks.check_email("ceo@alpha-trading.ch", company="Alpha Trading SA")
    by = {c["label"]: c for c in res["checks"]}
    assert by["Mail server (MX)"]["status"] == "ok"
    assert by["Anti-spoofing (SPF / DMARC)"]["detail"].startswith("SPF present · DMARC reject")
    assert by["Domain age"]["status"] == "ok" and by["Scam lists"]["status"] == "ok"
    assert "Name match" not in by
    free = checks.check_email("alpha.trading@gmail.com", company="Alpha Trading SA")
    assert (
        free["checks"][0]["status"] == "warn"
        and "free consumer mailbox" in free["checks"][0]["detail"]
    )
    throwaway = checks.check_email("x@mailinator.com")
    assert any(c["status"] == "alert" and "disposable" in c["detail"] for c in throwaway["checks"])
    assert checks.check_email("not-an-email")["valid"] is False


@respx.mock
def test_wallet_check_uses_sanctions_and_scam_lists(monkeypatch):
    _scam_lists()
    from app.connectors.official_sanctions import OfficialSanctionsConnector

    monkeypatch.setattr(OfficialSanctionsConnector, "screen", lambda self, e: [])
    res = checks.check_wallet("0x101ce0cedd142f199c9ef61739ae59b6611a0fc0")
    by = {c["label"]: c for c in res["checks"]}
    assert res["chain"] == "ETH" and by["Sanctions"]["status"] == "ok"
    assert by["Scam lists"]["status"] == "alert"
    assert checks.check_wallet("hello")["valid"] is False


def test_checks_endpoint_requires_something_to_check():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.post("/api/checks", json={}).status_code == 422
    res = client.post("/api/checks", json={"iban": "DE89370400440532013000"}).json()
    assert res["iban"]["valid"] and res["verdict"] in ("ok", "info", "warn")
