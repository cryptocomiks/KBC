"""Zefix (Swiss register), SEC EDGAR (US filings, 13D/13G owners), country risk, key findings."""

import json

import httpx
import respx

from app.connectors.sec_edgar import SecEdgarConnector
from app.connectors.zefix import ZefixConnector, translate_role
from app.graph.expander import Network
from app.insights import build_summary, build_timeline
from app.models import Entity, EntityType, Relationship, RelationType
from app.risk import config as risk_config
from app.risk.engine import RiskEngine
from app.settings import Settings

LIVE = Settings(live_sources=True)
ZEFIX = "https://www.zefix.admin.ch/ZefixREST/api/v1"

FIRM = {
    "name": "Alpina Trading AG",
    "ehraid": 111,
    "uidFormatted": "CHE-111.222.333",
    "chidFormatted": "CH-170-1",
    "legalSeat": "Zug",
    "legalFormId": 3,
    "status": "EXISTIEREND",
    "deleteDate": None,
    "purpose": "Handel mit Rohstoffen",
    "cantonalExcerptWeb": "https://zg.chregister.ch/x",
    "address": {
        "street": "Baarerstrasse",
        "houseNumber": "1",
        "swissZipCode": "6300",
        "town": "Zug",
    },
    "auditFirms": [{"name": "Revisa AG", "ehraid": 222, "uidFormatted": "CHE-999.888.777"}],
    "oldNames": [{"name": "Alpina Handels AG"}],
    "shabPub": [
        {
            "shabDate": "2021-03-01",
            "message": '<FT TYPE="F">Alpina Trading AG</FT>, in Zug. Eingetragene Personen neu oder mutierend: '
            "Muster, Hans, von Bern, in Zug, Mitglied des Verwaltungsrates, mit Einzelunterschrift; "
            "Rossi, Carla, italienische StaatsangehÃ¶rige, in Lugano, Gesellschafterin, ohne Zeichnungsberechtigung.",
            "mutationTypes": [{"key": "aenderungorgane"}],
        },
        {
            "shabDate": "2024-06-10",
            "message": "Alpina Trading AG, in Zug. Ausgeschiedene Personen und erloschene Unterschriften: "
            "Muster, Hans, von Bern, in Zug, Mitglied des Verwaltungsrates, mit Einzelunterschrift.",
            "mutationTypes": [{"key": "aenderungorgane"}],
        },
        {
            "shabDate": "2025-01-15",
            "message": "Alpina Trading AG, in Zug. Über die Gesellschaft wurde der Konkurs eröffnet.",
            "mutationTypes": [],
        },
    ],
}


@respx.mock
def test_zefix_company_officers_and_notices():
    respx.post(f"{ZEFIX}/firm/search.json").mock(
        return_value=httpx.Response(
            200, json={"list": [{k: v for k, v in FIRM.items() if k != "shabPub"}]}
        )
    )
    respx.get(f"{ZEFIX}/firm/111.json").mock(return_value=httpx.Response(200, json=FIRM))
    respx.get(f"{ZEFIX}/legalForm.json").mock(
        return_value=httpx.Response(
            200, json=[{"id": 3, "name": {"en": "Corporation", "de": "Aktiengesellschaft"}}]
        )
    )
    ZefixConnector._forms = None
    zefix = ZefixConnector(LIVE)

    [found] = zefix.search_company("Alpina Trading")
    assert found.jurisdiction == "CH" and found.registration_number == "CHE-111.222.333"
    company = zefix.get_company_details(found.id)
    assert company.legal_form == "Corporation" and "Alpina Handels AG" in company.aliases
    assert company.address == "Baarerstrasse 1, 6300 Zug"

    links = {link.entity.name: link.relationship for link in zefix.get_officers(found.id)}
    hans = links["Hans Muster"]
    assert hans.type == RelationType.OFFICER and hans.role.startswith("Board member")
    assert str(hans.start_date) == "2021-03-01" and str(hans.end_date) == "2024-06-10"
    carla = links["Carla Rossi"]  # GmbH/AG partner -> ownership link, mojibake repaired upstream
    assert carla.type == RelationType.SHAREHOLDER and carla.end_date is None
    assert links["Revisa AG"].role == "Auditor"

    docs = zefix.get_documents(company)
    assert any("insolvency" in d.flags for d in docs)  # "Konkurs eröffnet"
    assert any(d.kind == "register" for d in docs)


def test_translate_role():
    assert (
        translate_role("Präsident des Verwaltungsrates")
        == "Chair of the board (Präsident des Verwaltungsrates)"
    )
    assert translate_role("gérant") == "Managing director (gérant)"
    assert translate_role(None) is None


SUB = {
    "name": "Acme Robotics, Inc.",
    "cik": "0000123456",
    "sicDescription": "Industrial machinery",
    "stateOfIncorporation": "DE",
    "stateOfIncorporationDescription": "DE",
    "tickers": ["ACMR"],
    "exchanges": ["Nasdaq"],
    "formerNames": [{"name": "ACME ROBOTICS CORP"}],
    "addresses": {
        "business": {
            "street1": "1 Main St",
            "city": "Austin",
            "stateOrCountry": "TX",
            "zipCode": "78701",
        }
    },
    "filings": {
        "recent": {
            "form": ["SCHEDULE 13G/A", "10-K", "SC 13G", "8-K"],
            "filingDate": ["2026-05-01", "2026-02-20", "2020-02-14", "2026-01-10"],
            "accessionNumber": [
                "0000999999-26-000001",
                "0000123456-26-000002",
                "0000888888-20-000003",
                "0000123456-26-000004",
            ],
            "primaryDocument": [
                "xslSCHEDULE_13G_X02/primary_doc.xml",
                "acme-10k.htm",
                "filing.txt",
                "acme-8k.htm",
            ],
            "reportDate": ["", "2025-12-31", "", ""],
        }
    },
}
XML_13G = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g">
 <formData><coverPageHeader><eventDateRequiresFilingThisStatement>04/28/2026</eventDateRequiresFilingThisStatement></coverPageHeader>
  <coverPageHeaderReportingPersonDetails><reportingPersonName>Jane Founder</reportingPersonName>
   <citizenshipOrOrganization>X1</citizenshipOrOrganization><classPercent>12.5</classPercent><typeOfReportingPerson>IN</typeOfReportingPerson>
  </coverPageHeaderReportingPersonDetails>
  <coverPageHeaderReportingPersonDetails><reportingPersonName>Founder Holdings LLC</reportingPersonName>
   <classPercent>12.5</classPercent><typeOfReportingPerson>OO</typeOfReportingPerson>
  </coverPageHeaderReportingPersonDetails>
 </formData></edgarSubmission>"""


def _concept(val):
    return {
        "units": {
            "USD": [
                {
                    "end": "2025-12-31",
                    "val": val,
                    "form": "10-K",
                    "fp": "FY",
                    "filed": "2026-02-20",
                },
                {
                    "end": "2024-12-31",
                    "val": val / 2,
                    "form": "10-K",
                    "fp": "FY",
                    "filed": "2025-02-20",
                },
            ]
        }
    }


@respx.mock
def test_sec_profile_financials_owners_and_filings():
    respx.get("https://efts.sec.gov/LATEST/search-index").mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": {
                    "hits": [{"_id": "123456", "_source": {"entity": "Acme Robotics, Inc. (ACMR)"}}]
                }
            },
        )
    )
    respx.get("https://data.sec.gov/submissions/CIK0000123456.json").mock(
        return_value=httpx.Response(200, json=SUB)
    )
    concept = respx.get(
        url__regex=r"https://data\.sec\.gov/api/xbrl/companyconcept/CIK0000123456/us-gaap/(\w+)\.json"
    )

    def reply(request):
        name = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        values = {"Revenues": 4_000_000, "NetIncomeLoss": -250_000, "Assets": 9_000_000}
        return (
            httpx.Response(200, json=_concept(values[name]))
            if name in values
            else httpx.Response(404)
        )

    concept.mock(side_effect=reply)
    xml = respx.get(
        "https://www.sec.gov/Archives/edgar/data/123456/000099999926000001/primary_doc.xml"
    ).mock(return_value=httpx.Response(200, text=XML_13G))
    sec = SecEdgarConnector(LIVE)

    [hit] = sec.search_company("Acme Robotics")
    assert hit.name == "Acme Robotics, Inc." and hit.identifiers["CIK"] == "123456"
    company = sec.get_company_details(hit.id)
    assert company.jurisdiction == "US" and company.extra["tickers"] == "ACMR"
    assert (
        company.extra["revenue_usd"] == "4,000,000"
        and company.extra["net_income_usd"] == "-250,000"
    )
    assert [f["year"] for f in company.extra["financials"]] == ["2025", "2024"]
    assert str(company.last_accounts_date) == "2026-02-20"

    owners = {link.entity.name: link for link in sec.get_shareholders(hit.id)}
    assert xml.called
    jane = owners["Jane Founder"]
    assert jane.entity.type == EntityType.PERSON and jane.relationship.share_pct == 12.5
    assert str(jane.relationship.start_date) == "2026-04-28"
    assert owners["Founder Holdings LLC"].entity.type == EntityType.COMPANY

    docs = sec.get_documents(company)
    assert {d.title.split(" —")[0] for d in docs} >= {"SEC 10-K", "SEC 8-K", "SEC SCHEDULE 13G/A"}
    assert any(d.kind == "accounts" for d in docs)


def test_country_risk_factor_and_findings(tmp_path, monkeypatch):
    data = {
        "retrieved": "2026-09-24",
        "countries": {
            "PA": {
                "name": "Panama",
                "basel_aml_score": 6.4,
                "basel_aml_rank": 30,
                "cpi_score": 33,
                "cpi_year": 2024,
            },
            "CH": {
                "name": "Switzerland",
                "basel_aml_score": 4.5,
                "basel_aml_rank": 120,
                "cpi_score": 81,
                "cpi_year": 2024,
            },
        },
    }
    path = tmp_path / "country_risk.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(risk_config, "get_settings", lambda: Settings(country_risk_path=str(path)))
    risk_config.get_country_risk.cache_clear()
    try:
        ents = {
            "c1": Entity(
                id="c1", type=EntityType.COMPANY, name="Swiss Holding AG", jurisdiction="CH"
            ),
            "c2": Entity(id="c2", type=EntityType.COMPANY, name="Isthmus Corp", jurisdiction="PA"),
            "p1": Entity(id="p1", type=EntityType.PERSON, name="Ana Owner"),
        }
        rels = {
            "r1": Relationship(
                id="r1",
                type=RelationType.SHAREHOLDER,
                source_id="c2",
                target_id="c1",
                share_pct=100,
            ),
            "r2": Relationship(
                id="r2", type=RelationType.SHAREHOLDER, source_id="p1", target_id="c2", share_pct=60
            ),
        }
        net = Network(
            subject_id="c1",
            max_depth=2,
            max_nodes=10,
            entities=ents,
            relationships=rels,
            depth={"c1": 0, "c2": 1, "p1": 2},
        )
        risk = RiskEngine().assess(net)
        factor = next(f for f in risk.factors if f.key == "high_risk_country")
        assert factor.entities == ["c2"] and "Basel AML Index 6.40/10" in factor.evidence[0]

        summary = [f.text for f in build_summary(net, risk, risk_config.get_jurisdictions().name)]
        assert any(
            "Ultimately held at 60% by Ana Owner (person) via Isthmus Corp" in t for t in summary
        )
        assert build_timeline(net) == []  # no dated event in this network
    finally:
        risk_config.get_country_risk.cache_clear()
