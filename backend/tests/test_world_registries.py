"""Singapore ACRA, Israeli Registrar, Canada's Business Registries, CJEU judgments,
and the extended watchlists (background loading)."""

import httpx
import pytest
import respx

from app.connectors import open_datasets as od
from app.connectors.base import ConnectorError
from app.connectors.world_registries import (
    CA_API,
    CELLAR_SPARQL,
    IL_API,
    SG_API,
    AcraConnector,
    CanadaRegistriesConnector,
    CjeuConnector,
    IsraelRegistrarConnector,
)
from app.identifiers import Identifier
from app.models import CompanyStatus, Entity, EntityType
from app.settings import Settings

LIVE = Settings(live_sources=True)


@respx.mock
def test_singapore_acra():
    row = {
        "uen": "196800306E",
        "entity_name": "DBS BANK LTD.",
        "entity_type_desc": "Local Company",
        "uen_status_desc": "Registered",
        "uen_issue_date": "1968-07-16",
        "reg_street_name": "MARINA BOULEVARD",
        "reg_postal_code": "018982",
    }
    respx.get(url__startswith=SG_API).mock(
        return_value=httpx.Response(200, json={"result": {"records": [row]}})
    )
    conn = AcraConnector(LIVE)
    [c] = conn.search_company("DBS Bank")
    assert c.registration_number == "196800306E" and c.status == CompanyStatus.ACTIVE
    assert c.address.endswith("Singapore")
    assert conn.get_by_identifier(Identifier("registration", "196800306E", "UEN")).name == c.name


@respx.mock
def test_israel_registrar_flags_violating_companies():
    row = {
        "מספר חברה": 520013954,
        "שם חברה": "טבע תעשיות פרמצבטיות בע~מ",
        "שם באנגלית": "TEVA PHARMACEUTICAL INDUSTRIES LTD",
        "סוג תאגיד": "ישראלית חברה ציבורית",
        "סטטוס חברה": "פעילה",
        "תאריך התאגדות": "01/01/1944",
        "מפרה": "מפרה",
        "שם עיר": "תל אביב",
    }
    respx.get(url__startswith=IL_API).mock(
        return_value=httpx.Response(200, json={"result": {"records": [row]}})
    )
    [c] = IsraelRegistrarConnector(LIVE).search_company("Teva")
    assert c.name == "TEVA PHARMACEUTICAL INDUSTRIES LTD" and c.aliases
    assert c.status == CompanyStatus.ACTIVE and str(c.incorporation_date) == "1944-01-01"
    assert "violating" in c.extra["register_warning"]


@respx.mock
def test_canada_business_registries():
    doc = {
        "MRAS_ID": "CC_4261607",
        "Jurisdiction": "CC",
        "Company_Name": "SHOPIFY INC.",
        "Juri_ID": "4261607",
        "BN": "847871746RC0001",
        "Date_Incorporated": "2004-09-28",
        "Reg_office_city": "OTTAWA",
        "Reg_office_province": "Ontario",
        "Status_State": "Active",
        "Entity_Type": "Business Corporation",
    }
    respx.get(url__startswith=CA_API).mock(
        return_value=httpx.Response(200, json={"docs": [doc, doc]})
    )
    conn = CanadaRegistriesConnector(LIVE)
    [c] = conn.search_company("Shopify")
    assert c.identifiers["Business number"] == "847871746" and c.extra["register"].startswith(
        "federal"
    )
    assert (
        conn.get_by_identifier(Identifier("registration", "847871746", "BN")).name == "SHOPIFY INC."
    )


@respx.mock
def test_cjeu_judgments_for_companies_only():
    respx.get(url__startswith=CELLAR_SPARQL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "bindings": [
                        {
                            "celex": {"value": "62013CJ0536"},
                            "title": {
                                "value": "Judgment of the Court of 13 May 2015.#Gazprom OAO v Lietuvos Respublika."
                            },
                            "date": {"value": "2015-05-13"},
                        }
                    ]
                }
            },
        )
    )
    conn = CjeuConnector(LIVE)
    [d] = conn.get_documents(Entity(id="c", type=EntityType.COMPANY, name="Gazprom"))
    assert "Gazprom OAO" in d.title and "62013CJ0536" in d.url and str(d.date) == "2015-05-13"
    assert conn.get_documents(Entity(id="p", type=EntityType.PERSON, name="Jean Dupont")) == []


def test_extended_watchlists_never_block(monkeypatch):
    conn = od.OpenDatasetsExtendedConnector(Settings(live_sources=True, open_datasets_extended="x"))
    monkeypatch.setattr(conn, "wait_seconds", 0.2)
    monkeypatch.setattr(conn, "prefetch", lambda: None)  # nothing loads in this test
    monkeypatch.setattr(conn, "_state", od._State())
    with pytest.raises(ConnectorError, match="still loading"):
        conn.screen(Entity(id="c", type=EntityType.COMPANY, name="Acme"))
    assert conn._state is not od._STATE  # separate from the core lists
    assert od.OpenDatasetsExtendedConnector._state is not od.OpenDatasetsConnector._state
