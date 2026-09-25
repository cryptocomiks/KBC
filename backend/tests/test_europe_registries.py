"""Norway (Brønnøysund), Finland (PRH), Estonia (e-Äriregister), Czechia (ARES), Belgium (KBO)."""

import json

import httpx
import respx

from app.connectors.europe_registries import (
    ARES_API,
    BRREG_API,
    EE_API,
    KBO_DETAIL,
    KBO_SEARCH,
    PRH_API,
    AresConnector,
    AriregisterConnector,
    BrregConnector,
    KboConnector,
    PrhConnector,
    normalise_be,
    translate_cz_role,
    translate_no_role,
    valid_business_id,
    valid_ee_code,
    valid_ico,
    valid_orgnr,
)
from app.identifiers import Identifier, detect
from app.models import CompanyStatus, EntityType, RelationType
from app.settings import Settings

LIVE = Settings(live_sources=True)


def test_checksums():
    assert valid_orgnr("923609016") and not valid_orgnr("923609017")
    assert valid_business_id("0112038-9") and not valid_business_id("0112038-8")
    assert valid_ee_code("12417834") and not valid_ee_code("12417835")
    assert valid_ico("00177041") and not valid_ico("00177042")
    assert normalise_be("BE 0403.091.220") == "0403091220"
    assert normalise_be("403091220") == "0403091220"
    assert normalise_be("0403.091.221") is None


# ------------------------------------------------------------------ Norway
EQUINOR = {
    "organisasjonsnummer": "923609016",
    "navn": "EQUINOR ASA",
    "organisasjonsform": {"kode": "ASA", "beskrivelse": "Allmennaksjeselskap"},
    "historiskeNavn": [
        {"navn": "STATOIL ASA", "fraDato": "2001-05-11 08:32:09"},
        {"navn": "STATOILHYDRO ASA"},
        {"navn": "STATOIL ASA"},
    ],
    "hjemmeside": "www.equinor.com",
    "postadresse": {
        "land": "Norge",
        "landkode": "NO",
        "postnummer": "4035",
        "poststed": "STAVANGER",
        "adresse": ["Postboks 8500"],
    },
    "forretningsadresse": {
        "land": "Norge",
        "postnummer": "4035",
        "poststed": "STAVANGER",
        "adresse": ["Forusbeen 50"],
    },
    "registreringsdatoEnhetsregisteret": "1995-03-12",
    "stiftelsesdato": "1972-09-18",
    "naeringskode1": {"kode": "06.100", "beskrivelse": "Utvinning av råolje"},
    "konkurs": False,
    "underAvvikling": False,
}
ROLES = {
    "rollegrupper": [
        {
            "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
            "sistEndret": "2020-11-02",
            "roller": [
                {
                    "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                    "person": {
                        "fodselsdato": "1968-05-04",
                        "navn": {"fornavn": "Anders", "etternavn": "Opedal"},
                        "erDoed": False,
                    },
                    "avregistrert": False,
                }
            ],
        },
        {
            "type": {"kode": "STYR", "beskrivelse": "Styre"},
            "roller": [
                {
                    "type": {"kode": "LEDE", "beskrivelse": "Styrets leder"},
                    "person": {
                        "fodselsdato": "1960-04-26",
                        "navn": {"fornavn": "Jarle Kjell", "etternavn": "Roth"},
                    },
                },
                {
                    "type": {"kode": "MEDL", "beskrivelse": "Styremedlem"},
                    "person": {
                        "fodselsdato": "1970-01-01",
                        "navn": {"fornavn": "Old", "etternavn": "Member"},
                    },
                    "fratraadt": True,
                },
            ],
        },
        {
            "type": {"kode": "REVI", "beskrivelse": "Revisor"},
            "roller": [
                {
                    "type": {"kode": "REVI", "beskrivelse": "Revisor"},
                    "enhet": {
                        "organisasjonsnummer": "976389387",
                        "organisasjonsform": {"beskrivelse": "Aksjeselskap"},
                        "navn": ["ERNST & YOUNG AS"],
                    },
                }
            ],
        },
    ]
}


@respx.mock
def test_brreg_search_officers_and_identifier():
    respx.get(f"{BRREG_API}/enheter").mock(
        return_value=httpx.Response(200, json={"_embedded": {"enheter": [EQUINOR]}})
    )
    respx.get(f"{BRREG_API}/enheter/923609016").mock(
        return_value=httpx.Response(200, json={**EQUINOR, "konkurs": True})
    )
    respx.get(f"{BRREG_API}/enheter/923609016/roller").mock(
        return_value=httpx.Response(200, json=ROLES)
    )
    brreg = BrregConnector(LIVE)
    [found] = brreg.search_company("Equinor")
    assert found.id == "brreg:923609016" and found.jurisdiction == "NO"
    assert found.legal_form == "Allmennaksjeselskap" and found.status == CompanyStatus.ACTIVE
    assert found.address == "Forusbeen 50, 4035 STAVANGER, Norge"
    assert found.aliases == ["STATOIL ASA", "STATOILHYDRO ASA"]
    assert str(found.incorporation_date) == "1972-09-18"
    assert found.extra["website"] == "https://www.equinor.com"
    assert found.identifiers == {"Orgnr": "923609016"}

    links = {link.entity.name: link for link in brreg.get_officers(found.id)}
    assert set(links) == {"Anders Opedal", "Jarle Kjell Roth", "ERNST & YOUNG AS"}
    ceo = links["Anders Opedal"]
    assert ceo.relationship.role == "Chief executive (Daglig leder)"
    assert ceo.relationship.type == RelationType.OFFICER
    assert ceo.entity.birth_date == "1968-05-04" and ceo.entity.id.startswith("brreg:person:")
    assert ceo.relationship.target_id == found.id
    auditor = links["ERNST & YOUNG AS"]
    assert auditor.entity.type == EntityType.COMPANY and auditor.entity.id == "brreg:976389387"
    assert auditor.relationship.role.startswith("Auditor")

    [ident] = [i for i in detect("923 609 016")]
    company = brreg.get_by_identifier(ident)
    assert company.status == CompanyStatus.DISSOLVED  # konkurs
    docs = brreg.get_documents(company)
    assert docs[0].kind == "register" and docs[0].url.endswith("/923609016")
    assert any("insolvency" in d.flags for d in docs)


def test_translate_no_role():
    assert translate_no_role("Styrets leder") == "Chair of the board (Styrets leder)"
    assert translate_no_role("Varamedlem") == "Deputy board member (Varamedlem)"
    assert translate_no_role("Deltaker med delt ansvar").startswith("Partner")
    assert translate_no_role(None) is None


# ----------------------------------------------------------------- Finland
NOKIA = {
    "businessId": {"value": "0112038-9", "registrationDate": "1978-03-15", "source": "3"},
    "euId": {"value": "FIFPRO.0112038-9", "source": "1"},
    "names": [
        {"name": "Nokia Oyj", "type": "1", "registrationDate": "1997-09-01"},
        {"name": "Oy Nokia Ab", "type": "1", "endDate": "1997-08-31"},
        {"name": "Nokia Networks", "type": "3"},
        {"name": "Nokia Corporation", "type": "2"},
    ],
    "mainBusinessLine": {
        "type": "70100",
        "descriptions": [
            {"languageCode": "3", "description": "Activities of head offices"},
            {"languageCode": "1", "description": "Pääkonttorien toiminta"},
        ],
    },
    "website": {"url": "www.nokia.com"},
    "companyForms": [
        {
            "type": "17",
            "descriptions": [
                {"languageCode": "1", "description": "Julkinen osakeyhtiö"},
                {"languageCode": "3", "description": "Public limited company"},
            ],
        }
    ],
    "companySituations": [],
    "registeredEntries": [
        {"type": "1", "descriptions": [{"languageCode": "3", "description": "Registered"}]}
    ],
    "addresses": [
        {
            "type": 1,
            "street": "Karakaari",
            "buildingNumber": "7",
            "postCode": "02610",
            "postOffices": [{"city": "ESPOO", "languageCode": "1"}],
        }
    ],
}


@respx.mock
def test_prh_search_and_identifier():
    route = respx.get(PRH_API).mock(
        return_value=httpx.Response(200, json={"totalResults": 1, "companies": [NOKIA]})
    )
    prh = PrhConnector(LIVE)
    [found] = prh.search_company("Nokia")
    assert found.id == "prh:0112038-9" and found.name == "Nokia Oyj"
    assert found.aliases == ["Oy Nokia Ab", "Nokia Networks", "Nokia Corporation"]
    assert found.legal_form == "Public limited company"
    assert found.activity == "Activities of head offices"
    assert found.address == "Karakaari 7, 02610 ESPOO"
    assert found.status == CompanyStatus.ACTIVE and found.extra["accounts_unknown"]
    assert str(found.incorporation_date) == "1978-03-15"

    for ident in (Identifier("registration", "0112038-9", "x"), *detect("0112038-9")):
        assert prh.get_by_identifier(ident).registration_number == "0112038-9"
    assert route.calls.last.request.url.params["businessId"] == "0112038-9"
    assert prh.get_by_identifier(Identifier("uk_company", "01120388", "x")) is None

    bankrupt = {**NOKIA, "companySituations": [{"type": "KONK", "registrationDate": "2024-01-02"}]}
    company = prh._company(bankrupt)
    assert company.status == CompanyStatus.DISSOLVED
    assert any("insolvency" in d.flags for d in prh.get_documents(company))
    assert prh.get_officers(company.id) == []


# ----------------------------------------------------------------- Estonia
BOLT = {
    "company_id": 9000088952,
    "reg_code": 12417834,
    "name": "Bolt Technology OÜ",
    "historical_names": ["Taxify OÜ", "MTAKSO OÜ"],
    "status": "R",
    "legal_address": "Harju maakond, Tallinn, Kesklinna linnaosa, Vana-Lõuna tn 15",
    "zip_code": "10134",
    "legal_form": "5",
    "url": "https://ariregister.rik.ee/est/company/12417834/Bolt-Technology-OÜ",
}


@respx.mock
def test_ariregister_search_and_identifier():
    respx.get(EE_API).mock(
        return_value=httpx.Response(
            200,
            json={"status": "OK", "data": [{**BOLT, "reg_code": 12417835, "name": "Other"}, BOLT]},
        )
    )
    ee = AriregisterConnector(LIVE)
    found = ee.search_company("Bolt")[1]
    assert found.id == "ariregister:12417834" and found.jurisdiction == "EE"
    assert found.aliases == ["Taxify OÜ", "MTAKSO OÜ"]
    assert found.status == CompanyStatus.ACTIVE
    assert found.legal_form == "Private limited company (OÜ)"
    assert found.address.endswith("Vana-Lõuna tn 15, 10134")

    company = ee.get_by_identifier(detect("12417834")[0])
    assert company.name == "Bolt Technology OÜ"  # exact reg_code picked
    [doc] = ee.get_documents(company)
    assert doc.url == BOLT["url"] and doc.kind == "register"


# ----------------------------------------------------------------- Czechia
SKODA = {
    "ico": "00177041",
    "obchodniJmeno": "Škoda Auto a.s.",
    "sidlo": {
        "kodStatu": "CZ",
        "textovaAdresa": "tř. Václava Klementa 869, Mladá Boleslav II, 29301 Mladá Boleslav",
    },
    "pravniForma": "121",
    "datumVzniku": "1990-11-20",
    "dic": "CZ00177041",
    "seznamRegistraci": {"stavZdrojeVr": "AKTIVNI", "stavZdrojeIr": "NEEXISTUJICI"},
}


def _fo(first, last, born, nat="CZ"):
    return {
        "adresa": {"kodStatu": nat, "textovaAdresa": "Somewhere 1"},
        "datumNarozeni": born,
        "jmeno": first,
        "prijmeni": last,
        "statniObcanstvi": nat,
    }


VR = {
    "icoId": "00177041",
    "zaznamy": [
        {"primarniZaznam": False, "statutarniOrgany": []},
        {
            "primarniZaznam": True,
            "obchodniJmeno": [
                {"datumZapisu": "1998-02-06", "datumVymazu": "2023-03-31", "hodnota": "ŠKODA AUTO"},
                {"datumZapisu": "2023-03-31", "hodnota": "Škoda Auto a.s."},
            ],
            "statutarniOrgany": [
                {
                    "nazevOrganu": "Statutární orgán - představenstvo",
                    "clenoveOrganu": [
                        {
                            "datumZapisu": "2016-11-10",
                            "datumVymazu": "2021-10-13",
                            "clenstvi": {
                                "clenstvi": {
                                    "vznikClenstvi": "2016-08-01",
                                    "zanikClenstvi": "2021-09-30",
                                },
                                "funkce": {"nazev": "člen představenstva"},
                            },
                            "fyzickaOsoba": _fo("KLAUS-DIETER", "SCHÜRMANN", "1963-11-16", "DE"),
                        },
                        {  # rewritten entry (address change), then current entry
                            "datumZapisu": "2020-01-01",
                            "datumVymazu": "2022-05-01",
                            "clenstvi": {
                                "funkce": {
                                    "vznikFunkce": "2020-01-01",
                                    "nazev": "předseda představenstva",
                                }
                            },
                            "fyzickaOsoba": _fo("KLAUS", "ZELLMER", "1967-01-01", "DE"),
                        },
                        {
                            "datumZapisu": "2022-05-01",
                            "clenstvi": {"funkce": {"nazev": "předseda představenstva"}},
                            "fyzickaOsoba": _fo("KLAUS", "ZELLMER", "1967-01-01", "DE"),
                        },
                    ],
                }
            ],
            "ostatniOrgany": [
                {
                    "typOrganu": "DOZORCI_RADA",
                    "clenoveOrganu": [
                        {
                            "datumZapisu": "2021-01-01",
                            "clenstvi": {"funkce": {"nazev": "člen dozorčí rady"}},
                            "fyzickaOsoba": _fo("THOMAS", "SCHÄFER", "1970-04-01", "DE"),
                        }
                    ],
                },
                {
                    "typOrganu": "PROKURA",
                    "clenoveOrganu": [
                        {
                            "datumZapisu": "2019-01-01",
                            "nazevAngazma": "Prokurista",
                            "fyzickaOsoba": _fo("JOHANNES", "NEFT", "1969-09-26", "DE"),
                        }
                    ],
                },
            ],
            "akcionari": [
                {
                    "datumZapisu": "2000-08-09",
                    "datumVymazu": "2007-08-22",
                    "typOrganu": "AKCIONAR",
                    "clenoveOrganu": [
                        {
                            "datumZapisu": "2000-08-09",
                            "datumVymazu": "2007-08-22",
                            "nazevAngazma": "Akcionář",
                            "pravnickaOsoba": {
                                "adresa": {"kodStatu": "DE"},
                                "obchodniJmeno": "VOLKSWAGEN AKTIENGESELLSCHAFT",
                            },
                        }
                    ],
                }
            ],
            "spolecnici": [
                {
                    "spolecnik": [
                        {
                            "datumZapisu": "2015-01-01",
                            "osoba": {
                                "pravnickaOsoba": {
                                    "ico": "25788001",
                                    "obchodniJmeno": "Holding CZ s.r.o.",
                                    "adresa": {"kodStatu": "CZ"},
                                }
                            },
                            "podil": [
                                {
                                    "vklad": {"typObnos": "KORUNY", "hodnota": "200000;00"},
                                    "velikostPodilu": {"typObnos": "PROCENTA", "hodnota": "60;50"},
                                }
                            ],
                        }
                    ]
                }
            ],
        },
    ],
}


@respx.mock
def test_ares_search_officers_shareholders():
    search = respx.post(f"{ARES_API}/ekonomicke-subjekty/vyhledat").mock(
        return_value=httpx.Response(200, json={"pocetCelkem": 1, "ekonomickeSubjekty": [SKODA]})
    )
    respx.get(f"{ARES_API}/ekonomicke-subjekty/00177041").mock(
        return_value=httpx.Response(200, json=SKODA)
    )
    respx.get(f"{ARES_API}/ekonomicke-subjekty-vr/00177041").mock(
        return_value=httpx.Response(200, json=VR)
    )
    ares = AresConnector(LIVE)
    [found] = ares.search_company("Skoda Auto")
    assert json.loads(search.calls.last.request.content) == {
        "obchodniJmeno": "Skoda Auto",
        "pocet": 10,
    }
    assert found.id == "ares:00177041" and found.legal_form == "Joint-stock company (a.s.)"
    assert found.address.startswith("tř. Václava Klementa 869")
    assert found.identifiers == {"IČO": "00177041", "DIČ": "CZ00177041"}
    assert str(found.incorporation_date) == "1990-11-20"

    company = ares.get_by_identifier(detect("00177041")[0])
    assert company.aliases == ["ŠKODA AUTO"]

    officers = {link.entity.name: link.relationship for link in ares.get_officers(found.id)}
    assert set(officers) == {
        "Klaus-Dieter Schürmann",
        "Klaus Zellmer",
        "Thomas Schäfer",
        "Johannes Neft",
    }
    old = officers["Klaus-Dieter Schürmann"]
    assert old.role == "Board member (člen představenstva)"
    assert str(old.start_date) == "2016-08-01" and str(old.end_date) == "2021-09-30"
    chair = officers["Klaus Zellmer"]  # two register entries merged into one open relation
    assert chair.role.startswith("Chair of the board") and chair.end_date is None
    assert str(chair.start_date) == "2020-01-01"
    assert officers["Thomas Schäfer"].role.startswith("Supervisory board member")
    assert officers["Johannes Neft"].role.startswith("Authorised signatory (prokura)")
    person = next(
        link.entity for link in ares.get_officers(found.id) if link.entity.name == "Klaus Zellmer"
    )
    assert person.nationalities == ["DE"] and person.birth_date == "1967-01-01"
    assert person.address is None

    holders = {link.entity.name: link for link in ares.get_shareholders(found.id)}
    vw = holders["VOLKSWAGEN AKTIENGESELLSCHAFT"]
    assert vw.relationship.type == RelationType.SHAREHOLDER
    assert str(vw.relationship.end_date) == "2007-08-22" and vw.entity.jurisdiction == "DE"
    holding = holders["Holding CZ s.r.o."]
    assert holding.entity.id == "ares:25788001" and holding.relationship.share_pct == 60.5
    assert holding.relationship.end_date is None


def test_translate_cz_role():
    assert translate_cz_role("místopředseda dozorčí rady").startswith(
        "Vice-chair of the supervisory"
    )
    assert translate_cz_role("předseda dozorčí rady").startswith("Chair of the supervisory board")
    assert translate_cz_role("jednatel") == "Managing director (jednatel)"


# ----------------------------------------------------------------- Belgium
KBO_RESULTS = """<table><thead><tr><th>#</th><th>Status</th></tr></thead><tbody>
<tr class="odd"> <td>1</td> <td>ENT LP&nbsp; <br/> Active </td>
<td><a href="toonondernemingps.html?ondernemingsnummer=403091220"> 0403.091.220</a><br/>
<span class="upd">January 26, 1863<br/></span></td> <td class="nowrap"> - </td>
<td class="benaming">SOLVAY</td> <td class="">Rue de Ransbeek&nbsp;310<br/>1120&nbsp;Bruxelles<br/></td></tr>
<tr class="even"> <td>2</td> <td>ENT LP&nbsp; <br/> Active </td>
<td><a href="toonondernemingps.html?ondernemingsnummer=1005429150"> 1005.429.150</a><br/>
<span class="upd">January 5, 2024<br/></span></td> <td class="nowrap"> - </td>
<td class="benaming">ACP Immeuble rue Ernest Solvay 12 &agrave; Ixelles</td>
<td class="">Rue Ernest Solvay&nbsp;12<br/>1050&nbsp;Ixelles<br/></td></tr>
</tbody></table>"""

KBO_PAGE = """<table><tr><td class="I" colspan="4"><h2>General information</h2></td></tr>
<tr><td class="QL">Enterprise number:</td><td class="QL" colspan="3">0403.091.220</td></tr>
<tr><td class="RL">Status:</td><td class="RL" colspan="3"><strong><span class="pageactief">Active</span></strong></td></tr>
<tr><td class="QL">Legal situation:</td><td class="QL" colspan="3"><span class="pageactief">Normal situation</span>
<br/><span class="upd">Since January 26, 1863</span></td></tr>
<tr><td class="RL">Start date:</td><td class="RL" colspan="3">January 26, 1863</td></tr>
<tr><td class="QL">Name:</td><td class="QL" colspan="3">Solvay&nbsp;<br/><span class="upd">Name in French, since June 13, 2008</span></td></tr>
<tr><td class="RL">Registered seat's address:</td><td class="RL" colspan="3">Rue de Ransbeek&nbsp;310<br/>1120&nbsp;Bruxelles<br/><span class="upd">Since May 1, 2000</span></td></tr>
<tr><td class="QL">Web Address:</td><td class="QL" colspan="3"><a href="http://www.solvay.com">www.solvay.com</a></td></tr>
<tr><td class="RL">Legal form:</td><td class="RL" colspan="3">Public limited company<br/><span class="upd">Since May 1, 2019</span></td></tr>
<tr><td class="I" colspan="4"><h2>Functions</h2></td></tr>
<tr><td colspan="3"><table style="display: none" id="toonfctie" cellspacing="0" cellpadding="7" width="100%">
<tr><td class="RL">Director 											</td><td class="RL"> 													 AEBISCHER ,&nbsp;  Thomas&nbsp; 												</td><td class="RL"><span class="upd">Since December 8, 2023</span></td></tr>
<tr><td class="QL">Director 											</td><td class="QL"> 													 de Vogüé ,&nbsp;  Melchior&nbsp; 												</td><td class="QL"><span class="upd">Since December 8, 2023</span></td></tr>
<tr><td class="RL">Auditor </td><td class="RL"> <a href="toonondernemingps.html?ondernemingsnummer=446334711">0446.334.711</a> EY Bedrijfsrevisoren </td><td class="RL"><span class="upd">Since May 10, 2022</span></td></tr>
</table></td></tr></table>"""


@respx.mock
def test_kbo_search_details_functions():
    search = respx.get(KBO_SEARCH).mock(return_value=httpx.Response(200, text=KBO_RESULTS))
    detail = respx.get(KBO_DETAIL).mock(return_value=httpx.Response(200, text=KBO_PAGE))
    kbo = KboConnector(LIVE)
    found = kbo.search_company("Solvay")
    assert search.calls.last.request.url.params["searchWord"] == "Solvay"
    assert [f.id for f in found] == ["kbo:0403091220", "kbo:1005429150"]
    assert found[0].name == "SOLVAY" and found[0].status == CompanyStatus.ACTIVE
    assert found[0].address == "Rue de Ransbeek 310, 1120 Bruxelles"
    assert found[1].name == "ACP Immeuble rue Ernest Solvay 12 à Ixelles"
    assert found[0].identifiers == {"Enterprise number": "0403.091.220"}
    assert kbo.search_person("Solvay") == []

    for query in ("0403.091.220", "BE0403091220", "BE 0403 091 220"):
        [ident] = detect(query)
        company = kbo.get_by_identifier(ident)
        assert company.name == "Solvay" and company.legal_form == "Public limited company"
    assert detail.calls.last.request.url.params["ondernemingsnummer"] == "0403091220"
    assert str(company.incorporation_date) == "1863-01-26"
    assert company.address == "Rue de Ransbeek 310, 1120 Bruxelles"
    assert company.extra["website"] == "https://www.solvay.com"
    assert company.status == CompanyStatus.ACTIVE

    links = {link.entity.name: link for link in kbo.get_officers(company.id)}
    assert set(links) == {"Thomas Aebischer", "Melchior de Vogüé", "EY Bedrijfsrevisoren"}
    thomas = links["Thomas Aebischer"].relationship
    assert thomas.role == "Director" and str(thomas.start_date) == "2023-12-08"
    assert thomas.type == RelationType.OFFICER and thomas.target_id == "kbo:0403091220"
    ey = links["EY Bedrijfsrevisoren"]
    assert ey.entity.type == EntityType.COMPANY and ey.entity.id == "kbo:0446334711"
    assert ey.relationship.role == "Auditor"
    [doc] = kbo.get_documents(company)
    assert doc.url.endswith("ondernemingsnummer=0403091220&lang=en")
