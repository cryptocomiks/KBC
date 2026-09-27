"""SHAB/FOSC, VIES, CRO (Ireland), UK Find Case Law, RDAP, EU Transparency Register, and the
risk factors and search links they feed. Answers mirror the real APIs (probed live)."""

import gzip
import json
from datetime import date, timedelta

import httpx
import pytest
import respx

from app.connectors import free_sources as fs
from app.graph.links import register_links
from app.identifiers import Identifier
from app.models import CompanyStatus, Entity, EntityType
from app.settings import Settings

LIVE = Settings(live_sources=True)


def _company(name, jur=None, reg=None, **kw):
    return Entity(
        id=f"x:{name}",
        type=EntityType.COMPANY,
        name=name,
        jurisdiction=jur,
        registration_number=reg,
        **kw,
    )


def _shab(rubric, sub, title_de, title_en=None):
    return {
        "meta": {
            "id": f"id-{sub}",
            "rubric": rubric,
            "subRubric": sub,
            "publicationNumber": f"{sub}-1",
            "publicationDate": "2026-09-25T00:00:00.000Z",
            "cantons": ["ZH"],
            "title": {"de": title_de, "en": title_en or f"EN_{title_de}", "fr": f"FR_{title_de}"},
        }
    }


@respx.mock
def test_shab_keeps_company_notices_and_flags_bankruptcy():
    route = respx.get(url__startswith=fs.SHAB_API).mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    _shab(
                        "HR",
                        "HR02",
                        "Mutation Alpha Gerüstbau GmbH, Zürich",
                        "Change Alpha Gerüstbau GmbH, Zürich",
                    ),
                    _shab("KK", "KK01", "Konkurseröffnung Alpha Gerüstbau GmbH in Liquidation"),
                    _shab(
                        "SB", "SB01", "Zahlungsbefehl Alpha Gerüstbau GmbH"
                    ),  # debt enforcement: skipped
                    _shab("KK", "KK01", "Konkurseröffnung Beta Bau AG"),  # another company: skipped
                ]
            },
        )
    )
    docs = fs.ShabConnector(LIVE).get_documents(_company("Alpha Gerüstbau GmbH", "CH"))
    assert route.calls[0].request.url.params["publicationStates"] == "PUBLISHED"
    assert [d.title for d in docs] == [
        "Change Alpha Gerüstbau GmbH, Zürich",
        "Konkurseröffnung Alpha Gerüstbau GmbH in Liquidation",
    ]
    assert docs[1].flags == ["insolvency"] and "Bankruptcy" in docs[1].summary
    assert "change" in docs[0].summary and docs[0].date == date(2026, 9, 25)
    person = Entity(id="p", type=EntityType.PERSON, name="Hans Muster")
    assert fs.ShabConnector(LIVE).get_documents(person) == []


def test_vat_numbers_known_or_derived():
    fr = _company("SODIMAS", "FR", "303265045")
    assert fs.vat_numbers(fr) == [("FR", "40303265045")]  # key 40 computed from the SIREN
    be = _company("X", "BE", "0403.170.701")
    assert fs.vat_numbers(be) == [("BE", "0403170701")]
    de = _company("Y", "DE", identifiers={"VAT": "DE 811 569 869"})
    assert fs.vat_numbers(de) == [("DE", "811569869")]
    assert fs.vat_numbers(_company("Z", "CH", "CHE-1")) == []


@respx.mock
def test_vies_valid_invalid_and_name_mismatch(memory_cache):
    memory_cache.clear()
    respx.get(fs.VIES_API.format(cc="FR", number="40303265045")).mock(
        return_value=httpx.Response(
            200,
            json={
                "isValid": True,
                "userError": "VALID",
                "requestDate": "2026-09-27T10:20:11.851Z",
                "name": "SA SODIMAS",
                "address": "11 RUE AMPERE\n26600 PONT DE L ISERE",
            },
        )
    )
    [doc] = fs.ViesConnector(LIVE).get_documents(_company("Sodimas", "FR", "303265045"))
    assert "valid" in doc.title and doc.flags == [] and "PONT DE L ISERE" in doc.summary
    memory_cache.clear()
    respx.get(fs.VIES_API.format(cc="FR", number="40303265045")).mock(
        return_value=httpx.Response(
            200,
            json={"isValid": True, "userError": "VALID", "name": "OTHER HOLDING", "address": "---"},
        )
    )
    [doc] = fs.ViesConnector(LIVE).get_documents(_company("Sodimas", "FR", "303265045"))
    assert doc.flags == ["vat_name_mismatch"]
    memory_cache.clear()
    respx.get(fs.VIES_API.format(cc="FR", number="40303265045")).mock(
        return_value=httpx.Response(
            200, json={"isValid": False, "userError": "INVALID", "name": "---", "address": "---"}
        )
    )
    [doc] = fs.ViesConnector(LIVE).get_documents(_company("Sodimas", "FR", "303265045"))
    assert "NOT VALID" in doc.title and doc.flags == ["vat_invalid"]


RYANAIR = {
    "company_num": 104547,
    "company_name": "RYANAIR DESIGNATED ACTIVITY COMPANY",
    "company_status": "Normal ",
    "company_type": "DAC - Designated Activity Company (limited by shares)",
    "company_reg_date": "1984-11-28T00:00:00",
    "last_accounts_date": "2025-03-31T00:00:00",
    "company_address_1": "RYANAIR DUBLIN OFFICE",
    "company_address_2": "AIRSIDE BUSINESS PARK",
    "company_address_4": "SWORDS,DUBLIN",
    "comp_dissolved_date": None,
}


@respx.mock
def test_cro_search_identifier_status_and_filed_accounts():
    def answer(request):
        resource = request.url.params["resource_id"]
        if resource == fs.CRO_COMPANIES:
            return httpx.Response(200, json={"result": {"records": [RYANAIR]}})
        return httpx.Response(
            200,
            json={
                "result": {
                    "records": [
                        {
                            "submission_num": "SR1",
                            "submission_reg_date": "2025-01-20T00:00:00",
                            "submissions_accounts_to_date": "2024-03-31T00:00:00",
                        }
                    ]
                }
            },
        )

    respx.get(url__startswith=fs.CRO_API).mock(side_effect=answer)
    conn = fs.CroConnector(LIVE)
    [c] = conn.search_company("Ryanair")
    assert (
        c.status == CompanyStatus.ACTIVE
        and c.jurisdiction == "IE"
        and c.registration_number == "104547"
    )
    assert c.incorporation_date == date(1984, 11, 28) and c.last_accounts_date == date(2025, 3, 31)
    assert c.address.endswith("Ireland")
    assert conn.get_by_identifier(Identifier("registration", "104547", "n°")).name == c.name
    assert conn.get_by_identifier(Identifier("siren", "552100554", "SIREN")) is None
    docs = conn.get_documents(c)
    assert docs[0].kind == "register" and sum(d.kind == "accounts" for d in docs) == 3
    struck = conn._company({**RYANAIR, "company_status": "Strike Off Listed"})
    assert "Strike Off Listed" in struck.extra["register_warning"]


ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Carillion Plc (in liquidation) v Kpmg LLP</title>
<link href="https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/1" rel="alternate"/>
<published>2025-02-01T00:00:00+00:00</published><author><name>High Court (Commercial Court)</name></author></entry>
<entry><title>Coventry Partnership LLP v Avison Young (UK) Limited</title>
<link href="https://caselaw.nationalarchives.gov.uk/ewhc/tcc/2026/2319" rel="alternate"/>
<published>2026-09-15T00:00:00+00:00</published><author><name>High Court</name></author></entry>
</feed>"""


@respx.mock
def test_uk_case_law_keeps_cases_naming_the_party():
    route = respx.get(url__startswith=fs.CASELAW_ATOM).mock(
        return_value=httpx.Response(200, text=ATOM_FEED)
    )
    [doc] = fs.UkCaseLawConnector(LIVE).get_documents(_company("Carillion PLC", "GB"))
    assert route.calls[0].request.url.params["party"] == "Carillion"
    assert (
        doc.title.startswith("Carillion")
        and doc.flags == ["court"]
        and doc.summary.startswith("High Court")
    )
    private = Entity(id="p", type=EntityType.PERSON, name="John Smith")
    assert (
        fs.UkCaseLawConnector(LIVE).get_documents(private) == []
    )  # private individual: never queried


def _rdap(created: date):
    return {
        "events": [
            {"eventAction": "registration", "eventDate": f"{created}T04:00:00Z"},
            {"eventAction": "expiration", "eventDate": "2027-06-14T04:00:00Z"},
        ],
        "entities": [
            {
                "roles": ["registrar"],
                "vcardArray": [
                    "vcard",
                    [
                        ["version", {}, "text", "4.0"],
                        ["fn", {}, "text", "CSC Corporate Domains, Inc."],
                    ],
                ],
            }
        ],
    }


@respx.mock
def test_rdap_domain_age(monkeypatch, memory_cache):
    monkeypatch.setattr(fs, "websites", lambda e: ["newco.io"])
    memory_cache.clear()
    respx.get(fs.RDAP.format(domain="newco.io")).mock(
        return_value=httpx.Response(200, json=_rdap(date.today() - timedelta(days=40)))
    )
    [doc] = fs.RdapConnector(LIVE).get_documents(_company("NewCo Ltd", "GB"))
    assert doc.flags == ["young_domain"] and "CSC Corporate Domains" in doc.summary
    memory_cache.clear()
    respx.get(fs.RDAP.format(domain="newco.io")).mock(
        return_value=httpx.Response(200, json=_rdap(date(1998, 6, 15)))
    )
    [doc] = fs.RdapConnector(LIVE).get_documents(_company("NewCo Ltd", "GB"))
    assert doc.flags == [] and doc.date == date(1998, 6, 15)


@pytest.fixture
def transparency_file(tmp_path, monkeypatch):
    path = tmp_path / "tr.json.gz"
    orgs = [
        {
            "id": "5351887241-11",
            "name": "Google",
            "category": "Companies & groups",
            "country": "United States",
            "city": "Mountain View",
            "ep": 6,
            "fte": 7.5,
            "since": "2011-09-30",
        }
    ]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"export_date": "2026-09-26", "count": 1, "organisations": orgs}, f)
    monkeypatch.setattr(fs, "TR_FILE", path)
    monkeypatch.setattr(fs, "_TR_INDEX", None)
    yield path
    monkeypatch.setattr(fs, "_TR_INDEX", None)


def test_transparency_register_match(transparency_file):
    conn = fs.EuTransparencyRegisterConnector(LIVE)
    assert conn.status()[0]
    [doc] = conn.get_documents(_company("GOOGLE LLC", "US"))
    assert "5351887241-11" in doc.title and doc.flags == ["lobbying"]
    assert "6 person(s) accredited" in doc.summary and "export of 2026-09-26" in doc.source
    assert conn.get_documents(_company("Googleplex Holdings", "US")) == []


def test_transparency_register_disabled_without_index(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "TR_FILE", tmp_path / "missing.json.gz")
    enabled, msg = fs.EuTransparencyRegisterConnector(LIVE).status()
    assert not enabled and "not built" in msg


def test_search_links_gazette_and_press():
    docs = register_links(_company("Carillion PLC", "GB", "03782379"))
    titles = [d.title for d in docs]
    assert any("The Gazette" in t for t in titles) and any("Google News" in t for t in titles)
    news = next(d for d in docs if "Google News" in d.title)
    assert "money+laundering" in news.url and "%22Carillion+PLC%22" in news.url
    assert not any(
        "Gazette" in d.title for d in register_links(_company("Sodimas", "FR", "303265045"))
    )


def test_new_signals_feed_the_risk_score():
    from app.graph.expander import Network
    from app.models import Document
    from app.risk.engine import RiskEngine

    c = _company(
        "Shelly Ltd",
        "IE",
        "123456",
        extra={"register_warning": "Status in the Irish register: Strike Off Listed"},
    )
    c.documents = [
        Document(
            title="EU VAT number IE1 — NOT VALID (VIES)",
            kind="register",
            source="VIES",
            flags=["vat_invalid"],
        ),
        Document(
            title="Domain shelly.ie",
            kind="website",
            source="RDAP",
            summary="registered recently",
            flags=["young_domain"],
        ),
    ]
    net = Network(
        subject_id=c.id,
        max_depth=1,
        max_nodes=10,
        entities={c.id: c},
        relationships={},
        depth={c.id: 0},
        hits=[],
        queries=[],
        merges=[],
        warnings=[],
        truncated=False,
    )
    keys = {f.key for f in RiskEngine().assess(net).factors}
    assert {"vat_invalid", "young_domain", "register_warning"} <= keys
